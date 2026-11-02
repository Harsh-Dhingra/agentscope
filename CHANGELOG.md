# v0.7.0 — Drift from collected traces

- Tenant-scoped service/time cohorts with trace-backed observations and evidence links.
- Duration, reported tokens, tool error rates and explicit retries, with missing/insufficient evidence states.
- Snapshot comparisons, bounded windows, sample counts, KS effects and corrected permutation tests.
- Dashboard workflow and an explicitly synthetic OTLP fixture for demonstration. No automatic quality-degradation claims or scheduled alerts.

# v0.6.0 — Audited outbox maintenance

- Offline metadata inspection, exact-plan quarantine recovery and quarantine-age retention.
- Stable batch UIDs, conservative v0.5 migration, stale-plan rejection, and blocked replay of ambiguous/partial responses.
- State changes and OS-actor audit commit atomically; audit failures roll back the operation.
- Pending payloads are excluded from retention. No automatic deletion, credential rebinding, collector retention, or enterprise identity claims.

# v0.5.0 — Durable exporter and recovery

- Optional bounded SQLite sender outbox with redaction before disk, restart recovery, credential/destination binding and single-owner locking.
- Retry/backoff for transient OTLP failures; quarantine for permanent or partial responses; payload capacity and delivery counters.
- Collector storage failures now return retryable 503 instead of malformed-payload 400.
- Recovery example and read-only queue inspection CLI. Retention and distributed queues remain future work.

# v0.4.0 — Local identity and tenant access

- Authentication is now required by default (breaking change). Initialize local credentials before using the UI or API.
- Four roles, credential-bound tenant databases, revocable HttpOnly browser sessions, CSRF checks, and requester/reviewer separation.
- Tenant-scoped mutation audit and temporary MCP collector credentials.
- 74 backend tests and a production frontend build passed locally. Enterprise SSO, durable queues, retention and hybrid deployment remain future work.

# Changelog

Development history records actual work timestamps. Tags mark functional milestones.

## v0.3.0 — Review, replay, and controlled release

- Three bounded trace analyzers with evidence references, visible disagreement, and abstention on missing/invalid evidence.
- Built-in scenario replay, CLI regression checks, and CI failure exit codes.
- Two versioned configurations with server-computed evaluation gates, workload/config digests, and stale-proposal rejection.
- Stable 20% canary routing for synthetic requests, minimum validation gates, promotion, and manual/automatic rollback.
- Release event history and direct links from routed outcomes to trace inspection.

## v0.2.0 — Drift and tool policy

- Numeric reference/current window API; permutation-based distribution tests, effect sizes, multiple-testing correction, and charts.
- Seeded stationary, latency, quality, and retrieval-freshness comparisons.
- Deterministic policy gateway with synthetic principals/tools, explicit approval, and transactional idempotency.
- Persisted policy decision ledger and denied-execution evidence.

## v0.1.0 — Observability foundation

- OTLP HTTP ingestion, metadata filtering, SQLite storage, and React trace explorer.
- LangGraph incident workflow, MCP subprocess context propagation, and actual local Ollama inference.
- Failure diagnosis, baseline/controlled experiments, Docker recipe, and CI.
