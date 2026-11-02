# Outbox maintenance (v0.6)

Maintenance is an explicit, offline CLI operation on a sender outbox. It provides quarantine retention and reviewed recovery, not collector trace retention or an automatic deletion scheduler. Stop the exporter that owns the file before running commands. The same endpoint and original collector credential must be supplied; the OS file lock prevents concurrent ownership.

Set `AGENTSCOPE_EXPORT_TOKEN` privately, then inspect metadata:

```bash
.venv/bin/python -m agentscope.maintenance data/export-outbox.db list
.venv/bin/python -m agentscope.maintenance data/export-outbox.db audit
```

Both omit payloads and credentials. The CLI opens the outbox without starting a sender, and upgrades its schema if needed. Its default endpoint is `http://127.0.0.1:8765/v1/traces`; pass `--endpoint` before the subcommand if different. A missing outbox is rejected rather than created.

## Recover a quarantined batch

Fix the collector-side rejection first. Copy a batch UID from `list` and preview:

```bash
.venv/bin/python -m agentscope.maintenance data/export-outbox.db recover --batch BATCH_UID
```

The preview returns selected metadata, byte count, and `plan_digest`. Apply exactly that plan:

```bash
.venv/bin/python -m agentscope.maintenance data/export-outbox.db --apply PLAN_DIGEST recover --batch BATCH_UID
```

Recovery changes that batch to pending, retains its lifetime attempt count, and clears its retry deadline. It does not send data. Restart the exporter (or run the durable example with `--drain-only`) to deliver it. A second application is rejected because the batch is no longer quarantined. If delivery fails again, the new quarantine has a new retention start time.

Only batches quarantined on HTTP 4xx/5xx responses are eligible. Partial success, malformed success, and redirects remain blocked: their delivery outcome or destination is ambiguous. Replaying against an external collector still requires understanding its idempotency behavior. AgentScope deduplicates trace/span rows; that does not guarantee exactly-once external effects.

Credential rebinding/rotation is deliberately unsupported. The old credential must still be available to open its outbox; if revoked or expired, recovery alone cannot restore delivery. Do not edit the credential binding to bypass this boundary.

## Expire old quarantine

Choose an explicit cutoff in Unix seconds. Preview uses **quarantine time**, not original creation time, and excludes all pending batches:

```bash
.venv/bin/python -m agentscope.maintenance data/export-outbox.db expire --before CUTOFF_UNIX_SECONDS
.venv/bin/python -m agentscope.maintenance data/export-outbox.db --apply PLAN_DIGEST expire --before CUTOFF_UNIX_SECONDS
```

Use the identical cutoff for preview and apply. Nonfinite, negative, and future cutoffs are rejected. Expiry permanently removes selected payload rows and frees logical queue capacity. This is not secure erasure, immediate filesystem compaction, or deletion from backups. There is no automatic expiry and no pending-data deletion command.

Old v0.5 databases have no recorded quarantine time. Migration gives existing quarantine rows the migration time, conservatively starting their retention window then. It also assigns stable random batch UIDs, so reused SQLite row numbers cannot identify a different batch in a maintenance request.

## Audit and transaction boundary

Apply recomputes the plan inside an immediate SQLite transaction. Its digest covers operation, target, cutoff, credential/destination binding, batch UIDs, payload digests, attempts, and quarantine timestamps. Changed selection or metadata invalidates the preview. Empty plans cannot be applied.

Each successful operation stores the plan's safe metadata, timestamp, event ID, local OS UID and username in `maintenance_audit`, in the same transaction as the state change/deletion. If the audit write fails, the operation rolls back. Audit records do not contain payloads, credentials, or payload digests.

The OS UID identifies the local execution account. The username is descriptive, not a verified enterprise identity. This is not two-person approval, tamper-evident storage, or protection against an administrator editing the database. Audit metadata is retained indefinitely and excluded from the payload-capacity bound; manage disk capacity separately. Enterprise identity, audit archival, collector data retention, and distributed operation remain future work.
