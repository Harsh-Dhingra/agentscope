# Architecture and decisions

## The question this project answers

Can an engineer move from a visible failed agent outcome to the responsible tool/retrieval/model step, change the implementation, and rerun the same evaluation case?

The system stores measured execution events and explicit evaluator outputs. It never claims visibility into hidden model reasoning or the internal routing of a model provider.

## Trace contract

One trace represents one workflow execution. Named coordinator, researcher, analyst, model, tool, and evaluation spans describe observable operations. Parent IDs preserve nesting; links are retained for correlated work that is not a strict parent-child relationship. An MCP server span has the calling client's span as its remote parent.

The OTLP receiver accepts HTTP protobuf and JSON, not gRPC or compressed request bodies. IDs and timestamps are validated. Request size is bounded to 4 MiB and 2,000 spans. Duplicate `(trace_id, span_id)` records upsert rather than inflate counts. Links are stored and available in the API, but are not yet drawn as graph edges in the UI.

## Why OpenTelemetry?

It gives the project a standard context and export protocol, making independently instrumented processes joinable. The custom exporter applies the lab's privacy contract before serialization. A production integration would prefer standard batch/export machinery plus a carefully reviewed redaction processor and collector configuration.

## Why a custom store and UI?

This portfolio exercises telemetry ingestion, storage semantics, trace reconstruction, diagnosis, and outcome evaluation. Phoenix, Langfuse, and Opik remain sensible deployment choices for teams that need a maintained platform. Building this lab provides concrete engineering trade-offs to inspect; it does not demonstrate feature parity with those platforms.

## Why SQLite?

It makes setup reproducible and avoids operating a multi-service storage stack before the data model is useful. WAL permits readers during writes, and writes use a process lock and database transaction. This is a single-process development architecture, not a high-volume ingestion design.

At production scale, separate ingestion from analysis with a durable bounded queue; batch writes to a suitable analytical store; retain a transactional store for projects, evaluation configuration, and access control; add quotas, partitioning, retention, and index plans. Benchmark ingestion lag and query latency before choosing capacity numbers.

## Why a bounded workflow?

The LangGraph demo uses explicit nodes and controlled failure injection. It isolates the reliability behaviors under test and gives deterministic CI. The separate Ollama path shows real inference without making every test depend on a large model or a hosted API. Four fixtures validate specific regressions; they cannot estimate general model reliability.

## Diagnosis is evidence-based

- An error status signals a failed step, even when the workflow later recovers.
- `retrieval.current=false` identifies an explicitly obsolete source.
- An `eval.passed=false` span records a named failed assertion.
- At least three calls to the same tool trigger a retry warning; this is a heuristic and can flag legitimate repeated work.
- A missing parent is an informational partial-trace finding; it can arise from sampling or in-flight export.

No diagnosis is represented as certainty about hallucination. The response check in this workload is intentionally narrow: it looks for the expected retention duration together with applicable evidence, and checks truthful escalation when the tool fails.

## Runtime boundaries

The main app and MCP subprocess use separate tracer providers but share trace context. The worker returns a synthetic policy through MCP stdio and independently sends its span over HTTP. This is a real process boundary; it is not a tested cloud boundary.

An actual hybrid deployment would require enterprise credential lifecycle, a verified TLS topology, trusted resource attribution within each credential-bound tenant, durable buffering during outages, controlled export destinations, and a retention policy. Trace metadata such as `service.name` is supplied by the emitter and must not be treated as an authenticated identity.

## Failure behavior

Ingestion rejects invalid batches atomically. The bundled exporter counts failed batches; it does not retry or durably buffer them. The dashboard shows only received spans and may temporarily show an incomplete trace. Demo runs are serialized with an application lock to protect a local model from accidental concurrent runs.

Unexpected model-service failures produce a visible failed run. There is no cloud fallback. A later version should expose exporter failure counters and ingestion saturation in an operational health view.

## Identity boundary (v0.4)

Requests authenticate before selecting a tenant SQLite database. Four roles control reads, execution, approval, and ingestion. Trace resource attributes and client tenant headers cannot choose that database. Browser sessions use HttpOnly cookies and CSRF checks; approvals require a different subject from the requester. See [access control](access-control.md) for provisioning and limitations.

## Optional durable sender (v0.5)

Redacted protobuf → bounded SQLite outbox → HTTP worker → authenticated collector → tenant span transaction → acknowledgement → outbox deletion. Lost acknowledgements can cause replay; span IDs deduplicate storage. The sender persists retry deadlines and quarantines non-retryable responses. See [delivery semantics](durable-delivery.md).
