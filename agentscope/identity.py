"""Local high-entropy credentials and revocable sessions. Not an OIDC provider."""

import argparse
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

ROLES = {"viewer", "operator", "reviewer", "collector"}
PERMISSIONS = {
    "viewer": ["read"],
    "operator": ["read", "operate", "ingest"],
    "reviewer": ["read", "approve"],
    "collector": ["ingest"],
    "developer": ["read", "operate", "approve", "ingest"],
}
LABEL = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
SESSION_SECONDS = 8 * 3600


def fingerprint(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


class IdentityStore:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        os.chmod(path, 0o600)
        with self.db:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS tenants (id TEXT PRIMARY KEY, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS credentials (
                    id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, tenant TEXT NOT NULL REFERENCES tenants(id),
                    subject TEXT NOT NULL, role TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS sessions (
                    digest TEXT PRIMARY KEY, key_id TEXT NOT NULL REFERENCES credentials(id), csrf TEXT NOT NULL, expires REAL NOT NULL);
            """)

    def create_tenant(self, tenant):
        if not LABEL.fullmatch(tenant):
            raise ValueError(
                "Use a tenant name of 1–64 letters, digits, underscores or hyphens"
            )
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO tenants VALUES (?,?)", (tenant, time.time())
            )

    def issue(self, tenant, subject, role, ttl=30 * 86400):
        if role not in ROLES or not LABEL.fullmatch(subject):
            raise ValueError("Invalid subject or role")
        if ttl <= 0:
            raise ValueError("Credential lifetime must be positive")
        key = "as_" + secrets.token_urlsafe(32)
        key_id = str(uuid.uuid4())
        now = time.time()
        with self.lock, self.db:
            if not self.db.execute(
                "SELECT 1 FROM tenants WHERE id=?", (tenant,)
            ).fetchone():
                raise ValueError("Unknown tenant")
            self.db.execute(
                "INSERT INTO credentials VALUES (?,?,?,?,?,?,?,0)",
                (key_id, fingerprint(key), tenant, subject, role, now, now + ttl),
            )
        return {
            "key_id": key_id,
            "api_key": key,
            "tenant": tenant,
            "subject": subject,
            "role": role,
            "expires_at": now + ttl,
        }

    def _actor(self, row):
        return {
            "key_id": row["id"],
            "tenant": row["tenant"],
            "subject": row["subject"],
            "role": row["role"],
            "permissions": PERMISSIONS[row["role"]],
        }

    def authenticate(self, key):
        if not isinstance(key, str) or len(key) > 128:
            return None
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM credentials WHERE digest=? AND revoked=0 AND expires>?",
                (fingerprint(key), time.time()),
            ).fetchone()
        return self._actor(row) if row else None

    def session(self, secret):
        if not secret or len(secret) > 128:
            return None
        with self.lock:
            row = self.db.execute(
                "SELECT c.*, s.csrf, s.expires AS session_expires FROM sessions s JOIN credentials c ON s.key_id=c.id WHERE s.digest=? AND s.expires>? AND c.expires>? AND c.revoked=0",
                (fingerprint(secret), time.time(), time.time()),
            ).fetchone()
        return (
            {
                **self._actor(row),
                "csrf_token": row["csrf"],
                "session_expires": row["session_expires"],
            }
            if row
            else None
        )

    def create_session(self, key):
        with self.lock, self.db:
            actor = self.authenticate(key)
            if not actor or actor["role"] == "collector":
                raise ValueError("Invalid dashboard credential")
            secret = secrets.token_urlsafe(32)
            csrf = secrets.token_urlsafe(32)
            self.db.execute("DELETE FROM sessions WHERE expires<=?", (time.time(),))
            self.db.execute(
                "INSERT INTO sessions VALUES(?,?,?,?)",
                (
                    fingerprint(secret),
                    actor["key_id"],
                    csrf,
                    time.time() + SESSION_SECONDS,
                ),
            )
        return secret, {**actor, "csrf_token": csrf}

    def logout(self, secret):
        with self.lock, self.db:
            self.db.execute(
                "DELETE FROM sessions WHERE digest=?", (fingerprint(secret),)
            )

    def revoke(self, key_id):
        with self.lock, self.db:
            changed = self.db.execute(
                "UPDATE credentials SET revoked=1 WHERE id=?", (key_id,)
            ).rowcount
            self.db.execute("DELETE FROM sessions WHERE key_id=?", (key_id,))
        return bool(changed)

    def configured(self):
        with self.lock:
            return bool(
                self.db.execute(
                    "SELECT 1 FROM credentials WHERE revoked=0 AND expires>? LIMIT 1",
                    (time.time(),),
                ).fetchone()
            )

    @contextmanager
    def collector(self, actor):
        credential = self.issue(actor["tenant"], "mcp-worker", "collector", ttl=180)
        try:
            yield credential["api_key"]
        finally:
            self.revoke(credential["key_id"])

    def close(self):
        self.db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", default=os.environ.get("AGENTSCOPE_IDENTITY_DB", "data/identity.db")
    )
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--tenant", default="local")
    init.add_argument("--output", default="data/access-keys.json")
    issue = commands.add_parser("issue")
    issue.add_argument("--tenant", required=True)
    issue.add_argument("--subject", required=True)
    issue.add_argument("--role", choices=sorted(ROLES), required=True)
    issue.add_argument("--output", required=True)
    revoke = commands.add_parser("revoke")
    revoke.add_argument("--key-id", required=True)
    args = parser.parse_args()
    db = IdentityStore(args.db)
    try:
        if args.command == "revoke":
            if not db.revoke(args.key_id):
                parser.error("Credential not found")
            print("Credential and associated sessions revoked.")
            return
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        # O_EXCL prevents accidental replacement of credentials issued earlier.
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        keys = []
        try:
            db.create_tenant(args.tenant)
            if args.command == "init":
                keys = [
                    db.issue(args.tenant, f"{args.tenant[:48]}-{role}", role)
                    for role in ("operator", "reviewer", "viewer", "collector")
                ]
            else:
                keys = [db.issue(args.tenant, args.subject, args.role)]
            with os.fdopen(fd, "w") as file:
                json.dump({"tenant": args.tenant, "credentials": keys}, file, indent=2)
                file.write("\n")
        except Exception:
            for key in keys:
                db.revoke(key["key_id"])
            raise
        print(
            f"Credentials saved to {target}. Keep this file private; it is not a production identity provider."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
