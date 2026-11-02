# Public rollout: delivery plan and launch gates

AgentScope is currently a single-node engineering preview, not a production SaaS.
This plan treats a public launch as the target. No cloud resources have been provisioned.
Hosting-provider selection and customer-data capture policy are still pending.

## Phase 1 — provider-independent ingestion (implemented foundation)

Applications in AWS, GCP, Azure, or local environments can export OTLP/HTTP traces
(`/v1/traces`) and metadata-only logs (`/v1/logs`). Credentials issued by AgentScope
bind ingestion to one tenant; payload attributes cannot select a tenant. Collector
credentials cannot read telemetry. Use a separate credential per source, rotate it,
and revoke it if compromised. The current local credential registry is not cloud IAM.

Log ingestion supports protobuf and OTLP JSON, at most 4 MiB / 2,000 records per batch.
Free-text body, severity text, scope metadata, arbitrary resource attributes, and
cloud account IDs are omitted. Allowed operational attributes use the existing
allowlist and scrubber; `cloud.provider` accepts only `aws`, `gcp`, or `azure`.
Labels can still contain sensitive information: upstream policy must restrict their
values. This is data minimization, not a guarantee that every retained label is PII-free.

Timestamp and optional trace/span IDs are validated before any write. Batch writes
are atomic. Records deduplicate by a digest of retained metadata, so identical
records at the same timestamp collapse; this is unsuitable for exact billing counts.
`GET /api/logs?trace_id=<32 lowercase hex>&limit=100` returns up to 500 records,
newest first. Reads require a viewer/operator/reviewer session or credential.
This phase provides the API; a log explorer UI and cursor pagination remain pending.

Each tenant is limited to 100,000 stored log records. Capacity returns 429 with
Retry-After; storage failure returns 503. Retries of existing records consume no
additional capacity. Capacity is a safety ceiling, not an automatic retention system:
operators must resolve it before retrying can make progress. No record is silently
expired. Compression is currently rejected. Configure exporters with compression
`none`; durable collector queues must be monitored for saturation.

## Phase 2 — cloud onboarding and export adapters

Use customer-side collectors with outbound HTTPS to an authenticated ingestion
edge. Keep cloud-provider permissions inside the customer's account; do not request
root credentials, subscription Owner, or organization-wide log access.

| Source | Application telemetry | Existing provider logs (planned adapter) | Access boundary |
| --- | --- | --- | --- |
| AWS | OTel SDK → customer collector → AgentScope | Selected CloudWatch log groups → subscription destination → normalizer | Selected log groups and destination only; short-lived role credentials |
| GCP | OTel SDK → customer collector → AgentScope | Filtered Logging sink → Pub/Sub → normalizer | Dedicated sink writer and subscription consumer identities |
| Azure | OTel SDK → customer collector → AgentScope | Selected diagnostic settings → Event Hubs → normalizer | Dedicated hub consumer and scoped diagnostic configuration permissions |

A normalizer must validate source identity, map timestamps/severity/correlation IDs,
apply the content policy, then export OTLP. A cloud export is not necessarily OTLP.
These adapters, identity federation, checkpoints, dead-letter handling, and their
cloud integration tests are **not implemented**. Never label a provider “connected”
until a fresh test event arrives through its real route and the scoped identity is verified.

Onboarding should show region, selected sources, last event time, delivery lag,
permission validation, queue pressure, failure reason, and revoke/disconnect actions.
Test expired credentials, duplicate deliveries, source outages, malformed events,
and downstream backpressure. Monitor cloud egress and ingestion spend per tenant.

## Phase 3 — hosted private beta

Choose one hosting provider first; ingestion remains cloud-neutral. Proposed path:

Customer collectors → TLS ingestion edge → bounded durable queue → normalization
workers → tenant-indexed telemetry store. Browser → OIDC/BFF → authorized query API.
Use managed Postgres for control-plane metadata, object storage for encrypted raw
**sanitized** archives if required, and a measured telemetry store for query workloads.
Decide the telemetry engine after representative ingestion/query benchmarks.

Before inviting external users:

- OIDC issuer/audience verification, secure sessions, organization membership and
  tenant-scoped authorization tests; service identity rotation and revocation.
- TLS, explicit host allowlist, trusted-proxy configuration, network isolation,
  secret manager, and separate production/staging identities.
- Per-tenant byte/event rate limits, storage quotas, bounded queries, worker admission
  control, retry budgets, and an observable dead-letter queue.
- Explicit retention/deletion policy including backups, encryption/key ownership,
  tenant export, region selection, and opt-in approval before content capture.
- Automated migrations and rollback, backup/restore drill, recovery objectives,
  dependency/container scanning, and a reproducible signed release pipeline.
- Load/soak tests with expected tenant mix, failure injection, duplicate/reordering
  tests, isolation tests, and an incident/credential-compromise runbook.

Current SQLite files and local keys do not satisfy these hosted multi-user gates.
Keep the existing loopback deployment until the hosted boundary is implemented.

## Phase 4 — public availability

Private beta evidence determines launch capacity and SLOs. Proposed acceptance targets
(to confirm against workload and cost): 99.9% monthly ingestion availability, p95
accepted-event visibility under 10 seconds, and p95 filtered query latency under
2 seconds at a declared load. Track durable-ack failures separately from exporter
loss, queue age, rejected records, storage growth, and cost per million events.
Do not publish performance claims until measured with a documented benchmark.

Then ship the annotation → immutable dataset → experiment comparison workflow,
release gates, dashboards/alerts, and cloud-source management with the same identity
and audit boundaries. Human review and quality evaluations remain separate from
operational telemetry; a trace alone cannot establish factual correctness.

## Primary references

- [OpenTelemetry gateway deployment](https://opentelemetry.io/docs/collector/deploy/gateway/)
- [AWS CloudWatch Logs subscriptions](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/Subscriptions.html)
- [GCP Logging routing](https://docs.cloud.google.com/logging/docs/routing/overview)
- [Azure Monitor export to Event Hubs](https://learn.microsoft.com/en-us/azure/azure-monitor/platform/stream-monitoring-data-event-hubs)
