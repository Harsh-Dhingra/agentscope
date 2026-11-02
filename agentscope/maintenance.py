"""Offline, preview-first outbox retention and recovery with transactional audit."""

import argparse
import getpass
import hashlib
import json
import math
import os
import time
import uuid
from pathlib import Path

from .delivery import DurableDelivery


def plan(queue, operation, *, batch_uid=None, before=None):
    if operation not in {"recover", "expire"}:
        raise ValueError("Unknown operation")
    if queue.thread is not None:
        raise ValueError("Maintenance requires an offline outbox owner")
    if operation == "recover" and not batch_uid:
        raise ValueError("Recovery requires an exact batch UID")
    if operation == "expire" and (
        before is None
        or not math.isfinite(before)
        or before > time.time()
        or before < 0
    ):
        raise ValueError("Retention cutoff must be a finite past Unix timestamp")
    with queue.lock:
        if operation == "recover":
            rows = queue.db.execute(
                "SELECT * FROM batches WHERE batch_uid=? AND state='quarantined'",
                (batch_uid,),
            ).fetchall()
            if not rows:
                raise ValueError("Quarantined batch not found")
            reason = rows[0]["reason"] or ""
            if (
                not reason.startswith("http_")
                or not reason[5:].isdigit()
                or not 400 <= int(reason[5:]) <= 599
            ):
                raise ValueError(
                    "Ambiguous or partial delivery cannot be replayed automatically"
                )
        else:
            rows = queue.db.execute(
                "SELECT * FROM batches WHERE state='quarantined' AND quarantined_at<? ORDER BY batch_uid",
                (before,),
            ).fetchall()
        binding = queue.db.execute("SELECT binding FROM config WHERE id=1").fetchone()[
            0
        ]
        items = [
            {
                "uid": r["batch_uid"],
                "bytes": len(r["payload"]),
                "reason": r["reason"],
                "attempts": r["attempts"],
                "quarantined_at": r["quarantined_at"],
                "payload_digest": hashlib.sha256(r["payload"]).hexdigest(),
            }
            for r in rows
        ]
        manifest = {
            "operation": operation,
            "binding": binding,
            "before": before,
            "batch_uid": batch_uid,
            "items": items,
        }
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode()
        ).hexdigest()
        return {
            "operation": operation,
            "plan_digest": digest,
            "count": len(items),
            "payload_bytes": sum(x["bytes"] for x in items),
            "batches": [
                {k: v for k, v in item.items() if k != "payload_digest"}
                for item in items
            ],
        }


def apply(queue, operation, expected_digest, *, batch_uid=None, before=None):
    with queue.send_lock, queue.lock, queue.db:
        # Lock before preview validation so another writer cannot invalidate it.
        queue.db.execute("BEGIN IMMEDIATE")
        preview = plan(queue, operation, batch_uid=batch_uid, before=before)
        if preview["plan_digest"] != expected_digest:
            raise ValueError("Plan changed; preview again before applying")
        if not preview["count"]:
            raise ValueError("Plan selects no batches")
        for item in preview["batches"]:
            if operation == "recover":
                queue.db.execute(
                    "UPDATE batches SET state='pending', reason=NULL, due=0, quarantined_at=NULL WHERE batch_uid=? AND state='quarantined'",
                    (item["uid"],),
                )
            else:
                queue.db.execute(
                    "DELETE FROM batches WHERE batch_uid=? AND state='quarantined'",
                    (item["uid"],),
                )
        event = {
            **preview,
            "id": uuid.uuid4().hex,
            "created": time.time(),
            "actor": getpass.getuser(),
            "os_uid": os.getuid(),
        }
        queue.db.execute(
            "INSERT INTO maintenance_audit VALUES (?,?,?)",
            (event["id"], event["created"], json.dumps(event)),
        )
        queue._count(
            "manual_recoveries" if operation == "recover" else "retention_operations"
        )
        return event


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8765/v1/traces")
    parser.add_argument(
        "--apply",
        metavar="PLAN_DIGEST",
        help="Apply the exact previously previewed plan",
    )
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("list")
    commands.add_parser("audit")
    recover = commands.add_parser("recover")
    recover.add_argument("--batch", required=True)
    expire = commands.add_parser("expire")
    expire.add_argument(
        "--before",
        required=True,
        type=float,
        help="Exclusive quarantine-age cutoff as Unix seconds",
    )
    args = parser.parse_args()
    if not Path(args.path).is_file():
        parser.error("Outbox does not exist")
    token = os.environ.get("AGENTSCOPE_EXPORT_TOKEN")
    if not token:
        parser.error("Set AGENTSCOPE_EXPORT_TOKEN to the original collector credential")
    queue = None
    try:
        queue = DurableDelivery(args.path, args.endpoint, token, start_worker=False)
        if args.operation in {"list", "audit"}:
            if args.apply:
                raise ValueError("--apply is only for recover or expire")
            if args.operation == "list":
                result = [
                    dict(r)
                    for r in queue.db.execute(
                        "SELECT batch_uid,state,reason,attempts,created,quarantined_at,length(payload) AS payload_bytes FROM batches ORDER BY created"
                    )
                ]
            else:
                result = [
                    json.loads(r[0])
                    for r in queue.db.execute(
                        "SELECT payload FROM maintenance_audit ORDER BY created"
                    )
                ]
        else:
            options = (
                {"batch_uid": args.batch}
                if args.operation == "recover"
                else {"before": args.before}
            )
            result = (
                apply(queue, args.operation, args.apply, **options)
                if args.apply
                else plan(queue, args.operation, **options)
            )
        print(json.dumps(result, indent=2))
    except ValueError as exc:
        parser.error(str(exc))
    finally:
        if queue:
            queue.close()


if __name__ == "__main__":
    main()
