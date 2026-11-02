# Durable delivery (v0.5)

The optional Python exporter outbox persists already-redacted OTLP protobuf to a local SQLite WAL database before returning export success. A background worker sends committed batches; successful acknowledgement deletes them. Collector ingestion acknowledges only after its span transaction commits. Storage failures return HTTP 503 with Retry-After, while invalid payloads remain HTTP 400.

## Run and recover

Set `AGENTSCOPE_EXPORT_TOKEN` privately to a collector credential, then run:

```bash
.venv/bin/python examples/durable_instrument.py
.venv/bin/python -m agentscope.delivery data/export-outbox.db
```

To demonstrate an outage, stop your local collector and run the example. It exits with incomplete delivery and retains the batch. Restart the collector, then run:

```bash
.venv/bin/python examples/durable_instrument.py --drain-only
```

The drain-only run emits no new spans. It resumes the existing outbox with the same endpoint and credential, including persisted retry deadlines. The inspection CLI reports counts and failure categories without printing credentials or payloads.

To instrument another workflow, pass `outbox_path="data/my-agent-outbox.db"` to `create_tracer`, alongside `endpoint` and `export_token`. Call **`exporter.force_flush(timeout_millis=5000)`** to wait for delivery and inspect its Boolean result. `provider.shutdown()` stops the worker and preserves remaining batches; it does not promise to drain them. Do not rely on the simple span processor's provider-level flush as a delivery acknowledgement.

## Failure semantics

- Export success means committed to the local outbox, not received by the collector.
- Network errors and HTTP 429/502/503/504 retry with exponential backoff and jitter. Retry-After seconds or HTTP dates are honored as a minimum delay. Retries continue while the exporter runs.
- Other HTTP responses, malformed success responses, and partial-success reports are quarantined. Partial successes are not retried automatically, preventing replay of already accepted subsets.
- No response body or exception string is saved. Only fixed reason categories/status codes are recorded.
- A crash after collector commit but before sender acknowledgement can resend the batch. Delivery is **at least once**; AgentScope's trace/span primary key upserts prevent duplicate rows. This does not make arbitrary downstream effects exactly once.
- Pending and quarantined batches both count against capacity: default 1,000 batches and 32 MiB of payload. At capacity, new export returns FAILURE and increments rejection counters; accepted batches are never evicted. The SDK is not guaranteed to retry rejected exports. Monitor `failed_batches` and outbox counters.
- Limits bound retained payload, not total database/WAL/file-system bytes. Disk-full failures reject enqueue; filesystem capacity must be monitored separately.

## Ownership and privacy

One exporter owns each outbox through an OS file lock (macOS/Linux). Concurrent ownership is rejected. After process death, the OS releases the lock and a new exporter can resume. SQLite uses synchronous=FULL; persistence still depends on the underlying disk and filesystem honoring writes.

The queue binds to a digest of endpoint and credential. Opening it with a different destination or key fails, preventing accidental cross-tenant replay. Raw credentials are never persisted. Credential rotation requires a new outbox; old quarantined batches currently require an explicit offline recovery procedure. There is no automatic rebinding, requeue, purge, or retention operation in this release.

Files use mode 0600. Redaction precedes persistence, but permitted metadata is still sensitive and this is not disk encryption. Durable mode is opt-in; existing direct-store and best-effort HTTP callers retain their behavior. The short-lived MCP demo credential does not use a durable outbox.

## Verification and remaining work

Tests exercise abrupt process exit, restart, lost acknowledgements and deduplication, real HTTP outage recovery, retry deadlines, capacity rejection, quarantine, source-side redaction, endpoint/credential binding, and single-owner enforcement.

This is a single-node sender outbox, not a distributed broker or a central queue-management UI. Collector storage remains synchronous SQLite. Retention/deletion, audited quarantine recovery, distributed quotas, independent resource isolation, load benchmarks, disk-fault injection, and a real hybrid deployment remain future work.

Retry classification follows the [OTLP HTTP specification](https://opentelemetry.io/docs/specs/otlp/#otlphttp-response).
