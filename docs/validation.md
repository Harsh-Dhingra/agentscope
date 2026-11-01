# Validation record

Initial local validation performed on macOS using Python 3.14.4 and Node.js 25.6.1. CI is configured for Python 3.12 and Node.js 22 on Linux.

- Python backend tests cover redaction, serialization, OTLP ingestion/validation, duplicate delivery, trace integrity, failure scenarios, browser-origin and host restrictions, and the MCP subprocess integration.
- React/TypeScript production build completed successfully.
- Real MCP smoke run: completed with a shared trace across `incident-agent` and `mcp-runbook-worker`, containing 12 spans.
- Real Ollama smoke run using the locally installed `qwen3:8b`: returned the supported 30-day retention answer; reported 105 input-plus-output tokens; measured end-to-end run duration approximately 9.4 seconds on the initial run. This is a single smoke result, not a latency benchmark.
- Fixture comparison: baseline passed 1/4 scenarios and the controlled workflow passed 4/4. The checked-in `experiment.json` contains the actual report with individual run IDs, durations, answers, and assertions.

The Docker recipe and Linux compatibility are checked by the GitHub workflow. The initial [GitHub workflow](https://github.com/Harsh-Dhingra/agentscope/actions/runs/41320446778) passed both the Python/frontend job and Docker build/health job. A local Docker daemon was unavailable.

Open issues: broader held-out evaluation data, stochastic-model repetitions, calibration of diagnosis heuristics, load/backpressure tests, offline egress verification, delivery retries, retention, authentication and tenant isolation, and a real hybrid deployment.

Phase 2 adds seeded shift localization, stationary-control behavior, minimum-sample/nonfinite rejection, policy scope and role enforcement, idempotency-key collision rejection, and six concurrent approvals producing one synthetic restart. Browser checks exercised drift comparison, denied execution, and explicit approval.
