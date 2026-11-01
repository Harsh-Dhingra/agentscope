# AgentScope

**Follow an agent's execution. Diagnose failures. Verify the fix.**

AgentScope is a local-first observability and reliability lab for AI workflows. It accepts OpenTelemetry traces, reconstructs work across processes, flags evidence-backed failure patterns, and compares implementations against a reproducible evaluation dataset.

Built with **Python · FastAPI · React · TypeScript · OpenTelemetry · LangGraph · MCP · SQLite**.

This is an independent engineering portfolio project. It is not affiliated with other projects named AgentScope. The current release is a single-user development system; production and multicloud requirements are documented explicitly.

## Why build this?

A successful HTTP request can hide a failed AI task. A workflow can use an obsolete runbook, retry a broken dependency repeatedly, or answer confidently after its evidence lookup fails.

AgentScope connects those behaviors to their execution traces and evaluates the actual outcome. Its demo workload is incident analysis, keeping the observability platform independent of any one customer-service use case.

## What works today

- **OTLP/HTTP ingestion:** protobuf and JSON traces, parent IDs, links, execution times, error status, resource metadata, and duplicate-delivery upserts.
- **Trace explorer:** searchable runs, span waterfall, service attribution, metadata drill-down, explicit evaluation failures, and five-second refresh.
- **Source-side privacy controls:** bundled exporter drops unapproved attributes before network transport and suppresses raw exception messages. The collector filters incoming metadata again.
- **Real integrations:** a role-based LangGraph workload, a real MCP stdio worker with cross-process W3C trace propagation, and local Ollama inference with model-reported token counts.
- **Failure diagnosis:** failed steps, stale-evidence metadata, repeated calls, failed explicit assertions, and missing parent spans.
- **Reproducible experiments:** baseline versus controlled workflow for healthy execution, stale evidence, timeouts, and excessive retries.
- **Local storage:** SQLite WAL. No hosted observability account or paid model API is required for the fixture demo.

The diagnosis rules do **not** constitute a general hallucination detector. The experiment uses four authored scenarios with deterministic responses. The Ollama path performs actual model inference and is labeled separately.

## Run locally

Prerequisites: Python 3.12+ and Node.js 22+. The exact tested dependencies are in `requirements.lock` and `web/package-lock.json`.

```bash
git clone https://github.com/Harsh-Dhingra/agentscope.git
cd agentscope
make setup
make run
```

Open **http://127.0.0.1:8765**. Start with **Stale evidence → Baseline → Scripted fixture**. Then repeat with **With controls** and inspect the difference. The fixture mode requires no model download.

Without Make:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e . --no-deps
npm --prefix web ci
npm --prefix web run build
.venv/bin/python -m uvicorn agentscope.api:app --host 127.0.0.1 --port 8765
```

### Actual local inference

Install Ollama and download a supported local model during setup:

```bash
ollama pull qwen3:8b
```

With Ollama running locally, select **Local Ollama** in the dashboard. The model can also be configured using `AGENTSCOPE_OLLAMA_MODEL`; the default is `qwen3:8b`. Missing inference fails visibly; there is no scripted or hosted fallback.

For a deliberately offline runtime, configure the Ollama server with `OLLAMA_NO_CLOUD=1`, pre-download all dependencies/model weights, and test the whole deployment with outbound traffic blocked. This repository has not yet undergone a complete network-isolation audit. A successful local call alone does not prove zero egress.

### Cross-process MCP trace

Select **MCP · subprocess** and a healthy or stale-evidence scenario. The tool runs in a separate Python process and exports its server span back through OTLP/HTTP. The trace includes both `incident-agent` and `mcp-runbook-worker`.

The demo explicitly carries `traceparent` in its tool contract; it does not claim universal automatic MCP tracing. If the API uses a different port, set `AGENTSCOPE_DEMO_EXPORT_ENDPOINT` to its `/v1/traces` endpoint before starting it.

### Container

```bash
docker compose up --build
```

The published port is bound to host loopback. The image runs as a non-root user. The Compose configuration uses host Ollama when available. On Linux, a host Ollama bound only to `127.0.0.1` may not be reachable from the container; use the native setup for inference rather than broadly exposing the model server. Fixture runs and the MCP worker need no Ollama service.

## Instrument your own Python workflow

```python
from agentscope.telemetry import create_tracer

tracer, provider, exporter = create_tracer(
    service="my-agent",
    endpoint="http://127.0.0.1:8765/v1/traces",
)

with tracer.start_as_current_span("agent.run"):
    with tracer.start_as_current_span(
        "tool.lookup", attributes={"tool.name": "lookup"}
    ):
        pass  # your operation

provider.shutdown()
```

Run `python examples/instrument.py` with the API running. Standard OTLP exporters can also send protobuf/JSON to `/v1/traces`. Source-side filtering is guaranteed only for the bundled exporter; configure equivalent redaction in third-party instrumentation before sending data.

## Evaluation and verification

```bash
make test
make evaluate  # API must be running; writes data/experiment.json
```

The latest recorded fixture comparison passed **1/4 baseline** and **4/4 controlled** scenarios. These are regression results over the defined dataset, not production reliability, generalized model accuracy, or measured business impact. Inspect [validation notes](docs/validation.md) and the [recorded experiment](docs/experiment.json).

The suite checks source-side redaction, OTLP validation, idempotent ingestion, span parentage, error status, controlled retries, diagnosis, browser origin/host restrictions, and a real MCP subprocess round trip. CI builds the dashboard and container separately.

## Architecture

```mermaid
flowchart LR
    A[Your agent or LangGraph demo] --> S[OTel SDK + safe exporter]
    A -->|MCP stdio + W3C context| M[MCP worker process]
    M --> S2[OTel SDK + safe exporter]
    S -->|OTLP HTTP| I[FastAPI ingestion]
    S2 -->|OTLP HTTP| I
    I --> V[Validation + attribute filtering]
    V --> DB[(SQLite WAL)]
    DB --> D[Evidence-based diagnostics]
    DB --> UI[React trace explorer]
    D --> UI
    E[Versioned fault scenarios] --> A
    E --> R[Assertion report]
    R --> UI
    A --> L[Local Ollama model]
```

Read the [design decisions](docs/architecture.md), [privacy boundaries](docs/privacy.md), and [15-minute demo guide](docs/demo.md).

## Deliberate limits and next work

- Single user, loopback access, no authentication or tenant isolation. Do not expose this API publicly.
- No production queue, backpressure, retention scheduler, scalable analytical store, or delivery retry guarantee. The bundled synchronous exporter is for a small local lab.
- No deployed hybrid/multicloud topology. The HTTP exporter has an explicit remote opt-in; production would add authenticated collectors, encrypted transport, and network policy.
- No automatic model-cost estimates. The UI reports available token usage; local inference still consumes hardware and power.
- No measured debugging-time reduction, customer CSAT, or production savings. Those require a user study or deployment.
- The demo is a fixed role-based LangGraph workflow. It does not represent autonomous agents negotiating tasks with each other.
- Generalized grounding evaluation, larger held-out datasets, evaluator calibration, tenant authorization, and cost attribution are planned follow-ups.

## References

- [OpenTelemetry Python instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/)
- [OTLP specification](https://opentelemetry.io/docs/specs/otlp/)
- [W3C context propagation in OpenTelemetry](https://opentelemetry.io/docs/concepts/context-propagation/)
- [LangGraph](https://github.com/langchain-ai/langgraph)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Ollama chat API](https://docs.ollama.com/api/chat)

MIT licensed. Third-party dependencies retain their respective licenses.
