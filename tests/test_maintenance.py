import json
import os
import sqlite3
import subprocess
import sys
import time

import httpx
import pytest

from agentscope.delivery import DurableDelivery
from agentscope.maintenance import plan, apply

URL = "http://localhost/v1/traces"
TOKEN = "private-test-key"


@pytest.fixture
def queue(tmp_path):
    q = DurableDelivery(
        tmp_path / "outbox.db",
        URL,
        TOKEN,
        start_worker=False,
        transport=httpx.MockTransport(lambda r: httpx.Response(401)),
    )
    q.enqueue(b"secret-redacted-payload")
    q.deliver_once()
    yield q
    q.close()


def uid(q):
    return q.db.execute("SELECT batch_uid FROM batches").fetchone()[0]


def test_preview_and_exact_recovery_preserve_attempts(queue):
    batch = uid(queue)
    p = plan(queue, "recover", batch_uid=batch)
    assert queue.status()["quarantined"] == 1
    assert "secret-redacted-payload" not in json.dumps(p)
    e = apply(queue, "recover", p["plan_digest"], batch_uid=batch)
    assert e["os_uid"] == os.getuid()
    row = queue.db.execute("SELECT * FROM batches").fetchone()
    assert row["state"] == "pending" and row["attempts"] == 1 and row["due"] == 0
    assert queue.db.execute("SELECT COUNT(*) FROM maintenance_audit").fetchone()[0] == 1
    queue.transport = httpx.MockTransport(lambda r: httpx.Response(200))
    assert queue.deliver_once()
    assert queue.status()["pending"] == 0
    assert queue.status()["counters"]["delivered"] == 1
    with pytest.raises(ValueError):
        apply(queue, "recover", p["plan_digest"], batch_uid=batch)


def test_stale_plan_does_not_mutate(queue):
    batch = uid(queue)
    p = plan(queue, "recover", batch_uid=batch)
    with queue.db:
        queue.db.execute("UPDATE batches SET attempts=attempts+1")
    with pytest.raises(ValueError, match="changed"):
        apply(queue, "recover", p["plan_digest"], batch_uid=batch)
    assert queue.status()["quarantined"] == 1
    assert queue.db.execute("SELECT COUNT(*) FROM maintenance_audit").fetchone()[0] == 0


def test_audit_failure_rolls_back_recovery_and_expiry(queue):
    with queue.db:
        queue.db.execute(
            "CREATE TRIGGER fail_audit BEFORE INSERT ON maintenance_audit BEGIN SELECT RAISE(ABORT,'audit unavailable'); END"
        )
    for op, opts in [
        ("recover", {"batch_uid": uid(queue)}),
        ("expire", {"before": time.time()}),
    ]:
        p = plan(queue, op, **opts)
        with pytest.raises(sqlite3.IntegrityError):
            apply(queue, op, p["plan_digest"], **opts)
        assert queue.status()["quarantined"] == 1
        assert queue.db.execute("SELECT attempts FROM batches").fetchone()[0] == 1


def test_retention_excludes_pending_and_new_quarantine(queue):
    with queue.db:
        queue.db.execute("UPDATE batches SET quarantined_at=100")
    queue.enqueue(b"pending")
    cutoff = 200
    p = plan(queue, "expire", before=cutoff)
    assert p["count"] == 1
    apply(queue, "expire", p["plan_digest"], before=cutoff)
    assert queue.status()["pending"] == 1
    assert queue.status()["quarantined"] == 0
    queue.deliver_once()
    assert plan(queue, "expire", before=cutoff)["count"] == 0
    with pytest.raises(ValueError):
        apply(queue, "expire", p["plan_digest"], before=cutoff)


@pytest.mark.parametrize("cutoff", [float("nan"), float("inf"), -1, 1e20])
def test_invalid_retention_cutoff(queue, cutoff):
    with pytest.raises(ValueError):
        plan(queue, "expire", before=cutoff)


@pytest.mark.parametrize("reason", ["partial_success", "invalid_response", "http_302"])
def test_ambiguous_replay_blocked(queue, reason):
    with queue.db:
        queue.db.execute("UPDATE batches SET reason=?", (reason,))
    with pytest.raises(ValueError, match="cannot be replayed"):
        plan(queue, "recover", batch_uid=uid(queue))


def test_requarantine_has_new_retention_age(queue):
    batch = uid(queue)
    with queue.db:
        queue.db.execute("UPDATE batches SET quarantined_at=1")
    p = plan(queue, "recover", batch_uid=batch)
    apply(queue, "recover", p["plan_digest"], batch_uid=batch)
    queue.deliver_once()
    assert (
        queue.db.execute("SELECT quarantined_at FROM batches").fetchone()[0]
        > time.time() - 5
    )
    assert plan(queue, "expire", before=2)["count"] == 0


def test_old_schema_migration_is_conservative(tmp_path):
    import hashlib

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.executescript("""CREATE TABLE config(id INTEGER PRIMARY KEY,binding TEXT);
        CREATE TABLE batches(id INTEGER PRIMARY KEY,payload BLOB NOT NULL,created REAL NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,due REAL NOT NULL DEFAULT 0,state TEXT NOT NULL DEFAULT 'pending',reason TEXT);
        INSERT INTO batches VALUES(1,X'61',1,1,0,'quarantined','http_401');""")
        db.execute(
            "INSERT INTO config VALUES(1,?)",
            (hashlib.sha256(json.dumps([URL, TOKEN]).encode()).hexdigest(),),
        )
    q = DurableDelivery(path, URL, TOKEN, start_worker=False)
    try:
        assert len(uid(q)) == 32
        assert plan(q, "expire", before=time.time() - 10)["count"] == 0
    finally:
        q.close()


def test_cli_preview_apply_audit_and_ownership(tmp_path):
    path = tmp_path / "cli.db"
    q = DurableDelivery(
        path,
        URL,
        TOKEN,
        start_worker=False,
        transport=httpx.MockTransport(lambda r: httpx.Response(401)),
    )
    q.enqueue(b"private-payload")
    q.deliver_once()
    batch = uid(q)
    env = {**os.environ, "AGENTSCOPE_EXPORT_TOKEN": TOKEN}
    base = [
        sys.executable,
        "-m",
        "agentscope.maintenance",
        str(path),
        "--endpoint",
        URL,
    ]

    def cli(*args):
        return subprocess.run([*base, *args], env=env, capture_output=True, text=True)

    assert cli("list").returncode != 0
    q.close()
    preview = cli("recover", "--batch", batch)
    assert preview.returncode == 0
    digest = json.loads(preview.stdout)["plan_digest"]
    assert cli("--apply", digest, "recover", "--batch", batch).returncode == 0
    audit = cli("audit")
    assert len(json.loads(audit.stdout)) == 1
    assert TOKEN not in audit.stdout and "private-payload" not in audit.stdout
    env["AGENTSCOPE_EXPORT_TOKEN"] = "other-key"
    assert cli("list").returncode != 0
