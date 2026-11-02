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
