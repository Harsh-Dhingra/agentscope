"""Single-owner durable outbox for already-redacted OTLP protobuf batches."""

import fcntl
import hashlib
import json
import os
import random
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from email.utils import parsedate_to_datetime

import httpx
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceResponse,
)


class QueueFull(Exception):
    pass


class DurableDelivery:
    def __init__(
        self,
        path,
        endpoint,
        token=None,
        max_batches=1000,
        max_bytes=32 * 1024 * 1024,
        start_worker=True,
        transport=None,
    ):
        if max_batches < 1 or max_bytes < 1:
            raise ValueError("Queue limits must be positive")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.owner = open(path.with_suffix(path.suffix + ".lock"), "a+b")
        os.chmod(self.owner.name, 0o600)
        try:
            fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.owner.close()
            raise ValueError("Outbox already has an owner") from None
        self.lock = threading.RLock()
        self.send_lock = threading.Lock()
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.closed = False
        self.worker_error = False
        self.endpoint, self.token = endpoint, token
        self.max_batches, self.max_bytes = max_batches, max_bytes
        self.transport = transport
        self.thread = None
        try:
            self.db = sqlite3.connect(path, check_same_thread=False)
            os.chmod(path, 0o600)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY, binding TEXT);
                CREATE TABLE IF NOT EXISTS batches (
                    id INTEGER PRIMARY KEY, payload BLOB NOT NULL, created REAL NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, due REAL NOT NULL DEFAULT 0,
                    state TEXT NOT NULL DEFAULT 'pending', reason TEXT);
                CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
            """)
            # Credential binding prevents accidental replay into another tenant.
            binding = hashlib.sha256(json.dumps([endpoint, token]).encode()).hexdigest()
            with self.db:
                self.db.execute(
                    "INSERT OR IGNORE INTO config VALUES (1, ?)", (binding,)
                )
                if (
                    self.db.execute("SELECT binding FROM config WHERE id=1").fetchone()[
                        0
                    ]
                    != binding
                ):
                    raise ValueError(
                        "Outbox belongs to a different endpoint or credential"
                    )
            columns = {r[1] for r in self.db.execute("PRAGMA table_info(batches)")}
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                if "batch_uid" not in columns:
                    self.db.execute("ALTER TABLE batches ADD COLUMN batch_uid TEXT")
                if "quarantined_at" not in columns:
                    self.db.execute(
                        "ALTER TABLE batches ADD COLUMN quarantined_at REAL"
                    )
                # Legacy quarantine age is unknown: begin retention at migration.
                self.db.execute(
                    "UPDATE batches SET quarantined_at=? WHERE state='quarantined' AND quarantined_at IS NULL",
                    (time.time(),),
                )
                self.db.execute(
                    "UPDATE batches SET batch_uid=lower(hex(randomblob(16))) WHERE batch_uid IS NULL"
                )
                self.db.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS batches_uid ON batches(batch_uid)"
                )
                self.db.execute(
                    "CREATE TABLE IF NOT EXISTS maintenance_audit (id TEXT PRIMARY KEY, created REAL NOT NULL, payload TEXT NOT NULL)"
                )
            if start_worker:
                self.thread = threading.Thread(
                    target=self._work, name="agentscope-delivery", daemon=True
                )
                self.thread.start()
        except Exception:
            if hasattr(self, "db"):
                self.db.close()
            self.owner.close()
            raise

    def _count(self, name):
        self.db.execute(
            "INSERT INTO counters VALUES (?,1) ON CONFLICT(name) DO UPDATE SET value=value+1",
            (name,),
        )

    def enqueue(self, payload):
        with self.lock:
            if self.closed:
                raise RuntimeError("Outbox closed")
            with self.db:
                count, size = self.db.execute(
                    "SELECT COUNT(*), COALESCE(SUM(length(payload)),0) FROM batches"
                ).fetchone()
                full = count >= self.max_batches or size + len(payload) > self.max_bytes
                if full:
                    self._count("rejected")
                else:
                    self.db.execute(
                        "INSERT INTO batches(payload,created,batch_uid) VALUES (?,?,?)",
                        (payload, time.time(), uuid.uuid4().hex),
                    )
                    self._count("accepted")
            if full:
                raise QueueFull("Outbox capacity reached; batch was not accepted")
        self.wake.set()

    def status(self):
        with self.lock:
            states = dict(
                self.db.execute(
                    "SELECT state,COUNT(*) FROM batches GROUP BY state"
                ).fetchall()
            )
            size, oldest = self.db.execute(
                "SELECT COALESCE(SUM(length(payload)),0), MIN(created) FROM batches"
            ).fetchone()
            return {
                "pending": states.get("pending", 0),
                "quarantined": states.get("quarantined", 0),
                "payload_bytes": size,
                "oldest_age_seconds": max(0, time.time() - oldest) if oldest else 0,
                "max_batches": self.max_batches,
                "max_bytes": self.max_bytes,
                "worker_error": self.worker_error,
                "counters": dict(
                    self.db.execute("SELECT name,value FROM counters").fetchall()
                ),
            }

    def deliver_once(self):
        with self.send_lock:
            with self.lock:
                row = self.db.execute(
                    "SELECT * FROM batches WHERE state='pending' AND due<=? ORDER BY id LIMIT 1",
                    (time.time(),),
                ).fetchone()
            if row is None:
                return False
            result, reason, delay = "retry", "transport", 0
            try:
                headers = {"Content-Type": "application/x-protobuf"}
                if self.token:
                    headers["Authorization"] = "Bearer " + self.token
                with httpx.Client(
                    timeout=3,
                    trust_env=False,
                    follow_redirects=False,
                    transport=self.transport,
                ) as client:
                    response = client.post(
                        self.endpoint, content=row["payload"], headers=headers
                    )
                code = response.status_code
                if code == 200:
                    reply = ExportTraceServiceResponse()
                    try:
                        reply.ParseFromString(response.content)
                        if (
                            reply.partial_success.rejected_spans
                            or reply.partial_success.error_message
                        ):
                            result, reason = "quarantined", "partial_success"
                        else:
                            result, reason = "delivered", None
                    except Exception:
                        result, reason = "quarantined", "invalid_response"
                elif code in {429, 502, 503, 504}:
                    reason = f"http_{code}"
                    value = response.headers.get("Retry-After", "")
                    try:
                        delay = (
                            max(0, float(value))
                            if value.isdigit()
                            else max(
                                0,
                                parsedate_to_datetime(value).timestamp() - time.time(),
                            )
                        )
                    except (ValueError, TypeError, OverflowError):
                        delay = 0
                else:
                    result, reason = "quarantined", f"http_{code}"
            except httpx.HTTPError:
                pass
            with self.lock, self.db:
                if result == "delivered":
                    self.db.execute("DELETE FROM batches WHERE id=?", (row["id"],))
                    self._count("delivered")
                elif result == "quarantined":
                    self.db.execute(
                        "UPDATE batches SET state='quarantined', reason=?, attempts=attempts+1, quarantined_at=? WHERE id=?",
                        (reason, time.time(), row["id"]),
                    )
                    self._count("quarantined")
                else:
                    backoff = min(60, 2 ** min(row["attempts"], 6)) * random.uniform(
                        0.8, 1.2
                    )
                    self.db.execute(
                        "UPDATE batches SET attempts=attempts+1,due=?,reason=? WHERE id=?",
                        (time.time() + max(backoff, delay), reason, row["id"]),
                    )
                    self._count("retries")
            return True

    def _work(self):
        while not self.stop.is_set():
            try:
                if self.deliver_once():
                    self.worker_error = False
                    continue
                self.worker_error = False
            except Exception:
                # Do not leak payloads, credentials, or exception text into logs.
                self.worker_error = True
            self.wake.wait(0.2)
            self.wake.clear()

    def flush(self, timeout_millis=30000):
        deadline = time.monotonic() + max(0, timeout_millis) / 1000
        self.wake.set()
        while True:
            status = self.status()
            if not status["pending"]:
                return status["quarantined"] == 0
            if time.monotonic() >= deadline:
                return False
            self.stop.wait(min(0.05, max(0, deadline - time.monotonic())))

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join()
        with self.send_lock, self.lock:
            self.db.close()
            self.owner.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Inspect an outbox without exposing payloads or credentials"
    )
    parser.add_argument("path")
    args = parser.parse_args()
    uri = Path(args.path).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        print(
            json.dumps(
                {
                    "states": dict(
                        db.execute("SELECT state,COUNT(*) FROM batches GROUP BY state")
                    ),
                    "reasons": dict(
                        db.execute(
                            "SELECT COALESCE(reason,'queued'),COUNT(*) FROM batches GROUP BY reason"
                        )
                    ),
                    "counters": dict(db.execute("SELECT name,value FROM counters")),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
