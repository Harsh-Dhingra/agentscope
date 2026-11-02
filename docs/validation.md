# Validation record

Initial local validation performed on macOS using Python 3.14.4 and Node.js 25.6.1. CI is configured for Python 3.12 and Node.js 22 on Linux.

- Python backend tests cover redaction, serialization, OTLP ingestion/validation, duplicate delivery, trace integrity, failure scenarios, browser-origin and host restrictions, and the MCP subprocess integration.
- React/TypeScript production build completed successfully.
- Real MCP smoke run: completed with a shared trace across `incident-agent` and `mcp-runbook-worker`, containing 12 spans.
- Real Ollama smoke run using the locally installed `qwen3:8b`: returned the supported 30-day retention answer; reported 105 input-plus-output tokens; measured end-to-end run duration approximately 9.4 seconds on the initial run. This is a single smoke result, not a latency benchmark.
- Fixture comparison: baseline passed 1/4 scenarios and the controlled workflow passed 4/4. The checked-in `experiment.json` contains the actual report with individual run IDs, durations, answers, and assertions.

The Docker recipe and Linux compatibility are checked by the GitHub workflow. The initial [GitHub workflow](https://github.com/Harsh-Dhingra/agentscope/actions/runs/41320446778) passed both the Python/frontend job and Docker build/health job. A local Docker daemon was unavailable.

Open issues: broader held-out evaluation data, stochastic-model repetitions, calibration of diagnosis heuristics, load/backpressure tests, offline egress verification, delivery retries, retention, enterprise identity federation, and a real hybrid deployment.

Phase 2 adds seeded shift localization, stationary-control behavior, minimum-sample/nonfinite rejection, policy scope and role enforcement, idempotency-key collision rejection, and six concurrent approvals producing one synthetic restart. Browser checks exercised drift comparison, denied execution, and explicit approval.

Phase 3 local verification: **44 tests passed**, the TypeScript production build passed, and the CLI check passed all four controlled cases. Tests include analyzer errors and fabricated evidence, case replay, blocked failing configurations, source-digest changes, stale proposal rejection, stable routing, minimum canary samples, promotion/rollback, injected candidate failure, and the HTTP release workflow. The browser walkthrough reproduced failed gates, approved canary startup, five candidate validations, promotion, manual rollback, and automatic rollback after a synthetic availability failure.

The actual local [release walkthrough record](release-validation.json) includes evaluated proposals, routed execution IDs, promotion, and rollback events. Desktop (1365 px) and mobile (390 px) layouts were inspected; the new mobile pages had no horizontal document overflow. No browser console errors were observed during the final UI check.

Phase 4a local verification: **74 tests passed** on Python 3.12; the TypeScript production build passed. New coverage includes anonymous access denial, tenant spoofing and case-sensitive tenant IDs, collector-only ingestion, cross-tenant and self-approval denial, browser CSRF/origin enforcement, session rotation/logout/revocation, secret-free audit records, credential expiry, and private CLI output files. The real MCP integration uses a temporary collector credential and checks its revocation. Browser testing confirmed operator request creation, disabled self-approval, and approval by a separate reviewer with both identities displayed.

Phase 4b / v0.5: **95 tests passed** on Python 3.12. New tests cover an abrupt child-process exit followed by outbox recovery, real loopback HTTP outage/restart, lost acknowledgements with idempotent collector storage, retryable status codes and persisted Retry-After deadlines, permanent/partial/malformed response quarantine, payload and batch capacity, single-owner locking, endpoint/credential mismatch rejection, source redaction before disk, background flush/shutdown, and storage-failure HTTP 503. This is functional recovery evidence, not a throughput benchmark or proof against physical disk failure.
