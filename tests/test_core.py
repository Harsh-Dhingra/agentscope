import pytest
from fastapi.testclient import TestClient
from opentelemetry.trace import Status, StatusCode, SpanKind
from agentscope.api import create_app
from agentscope.demo import execute, experiment, RunRequest
from agentscope.privacy import safe_attributes
from agentscope.store import Store
from agentscope.telemetry import create_tracer, encode_spans, decode_otlp, SafeExporter
from agentscope.analysis import diagnose
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor


@pytest.fixture
def store():
    db = Store(":memory:")
    yield db
    db.close()


@pytest.fixture
def client(tmp_path):
    with TestClient(
        create_app(str(tmp_path / "core.db"), auth_mode="development"),
        base_url="http://localhost",
    ) as c:
        yield c


def request_fixture():
    tracer, provider, _ = create_tracer()
    memory = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    with tracer.start_as_current_span("parent", kind=SpanKind.SERVER) as parent:
        parent.set_attribute("input.value", "sensitive content")
        parent.set_attribute("service.name", "person@example.com")
        with tracer.start_as_current_span("child", kind=SpanKind.CLIENT) as child:
            child.set_attribute("tool.name", "lookup")
            child.set_status(Status(StatusCode.ERROR, "private error message"))
            child.add_event(
                "exception",
                {"exception.type": "TimeoutError", "exception.message": "very secret"},
            )
    request = encode_spans(memory.get_finished_spans())
    provider.shutdown()
    return request


def test_allowlist_drops_content_and_masks_known_patterns():
    result = safe_attributes(
        {
            "prompt": "secret",
            "gen_ai.request.model": "x",
            "tool.result": "contact me@example.com bearer secretvalue",
            "unknown": 123,
        }
    )
    assert "prompt" not in result
    assert result["tool.result"] == "contact [EMAIL] [REDACTED]"
    assert result["agentscope.dropped_attributes"] == 2


def test_redaction_happens_before_serialization():
    raw = request_fixture().SerializeToString()
    for sensitive in [
        b"sensitive content",
        b"private error message",
        b"very secret",
        b"person@example.com",
    ]:
        assert sensitive not in raw


def test_parentage_kinds_and_error_survive_otlp():
    spans = decode_otlp(request_fixture())
    child, parent = spans
    assert child["parent_id"] == parent["span_id"]
    assert child["trace_id"] == parent["trace_id"]
    assert child["kind"] == 3 and parent["kind"] == 2
    assert child["status"] == "ERROR"
    assert child["events"][0]["attributes"] == {
        "exception.type": "TimeoutError",
        "agentscope.dropped_attributes": 1,
    }


def test_ingestion_is_idempotent(client):
    payload = request_fixture().SerializeToString()
    for _ in range(2):
        assert (
            client.post(
                "/v1/traces",
                content=payload,
                headers={"Content-Type": "application/x-protobuf"},
            ).status_code
            == 200
        )
    traces = client.get("/api/traces").json()
    assert len(traces) == 1 and traces[0]["span_count"] == 2


def test_otlp_json_hex_ids_and_validation(client):
    span = {
        "traceId": "01" * 16,
        "spanId": "02" * 8,
        "name": "external",
        "startTimeUnixNano": "100",
        "endTimeUnixNano": "200",
        "attributes": [{"key": "prompt", "value": {"stringValue": "secret"}}],
    }
    body = {"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]}
    assert client.post("/v1/traces", json=body).status_code == 200
    result = client.get("/api/traces/" + "01" * 16).json()
    assert "prompt" not in result["spans"][0]["attributes"]
    span["traceId"] = "abcd"
    assert client.post("/v1/traces", json=body).status_code == 400


def test_invalid_payload_and_unsupported_content(client):
    assert (
        client.post(
            "/v1/traces",
            content=b"not protobuf",
            headers={"Content-Type": "application/x-protobuf"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/v1/traces", content="hello", headers={"Content-Type": "text/plain"}
        ).status_code
        == 415
    )
    assert client.get("/api/traces/absent").status_code == 404


def test_untrusted_browser_origin_cannot_start_work(client):
    assert (
        client.post(
            "/api/runs", json={}, headers={"Origin": "https://attacker.example"}
        ).status_code
        == 403
    )


def test_untrusted_host_rejected(client):
    assert (
        client.get("/api/health", headers={"Host": "attacker.example"}).status_code
        == 400
    )


def test_export_requires_remote_opt_in():
    with pytest.raises(ValueError):
        SafeExporter(endpoint="https://example.com/v1/traces")
    with pytest.raises(ValueError):
        SafeExporter(endpoint="http://user:password@localhost/v1/traces")


@pytest.mark.parametrize(
    "scenario", ["healthy", "stale_evidence", "tool_timeout", "retry_loop"]
)
async def test_guarded_scenarios_and_trace_integrity(store, scenario):
    result = await execute(RunRequest(scenario=scenario, variant="guarded"), store)
    assert result["passed"]
    spans = store.spans(result["trace_id"])
    assert spans and sum(s["parent_id"] is None for s in spans) == 1
    ids = {s["span_id"] for s in spans}
    assert all(not s["parent_id"] or s["parent_id"] in ids for s in spans)
    assert result["export_failures"] == 0


async def test_stale_evidence_failure_and_diagnosis(store):
    result = await execute(
        RunRequest(scenario="stale_evidence", variant="baseline"), store
    )
    assert not result["passed"] and "90 days" in result["answer"]
    findings = diagnose(store.spans(result["trace_id"]))
    assert any(f["title"] == "Stale evidence retrieved" for f in findings)
    assert any(f["title"] == "Evaluation assertion failed" for f in findings)


async def test_retries_are_measured_and_bounded(store):
    baseline = await execute(
        RunRequest(scenario="retry_loop", variant="baseline"), store
    )
    guarded = await execute(RunRequest(scenario="retry_loop", variant="guarded"), store)
    for r, n in [(baseline, 4), (guarded, 2)]:
        spans = store.spans(r["trace_id"])
        assert len([s for s in spans if s["name"] == "tool.lookup_runbook"]) == n
    assert guarded["outcome"] == "escalated"


async def test_comparison_reports_real_fixture_runs(store):
    report = await experiment(store)
    assert report["summary"] == {
        "baseline": {"passed": 1, "total": 4},
        "guarded": {"passed": 4, "total": 4},
    }
    assert len(store.list("runs")) == 8
    assert all(store.spans(r["trace_id"]) for r in report["rows"])


def test_request_disallows_arbitrary_model_endpoint(client):
    assert (
        client.post("/api/runs", json={"endpoint": "http://example.com"}).status_code
        == 422
    )


def test_max_payload(client):
    assert (
        client.post(
            "/v1/traces",
            content=b"x" * (4 * 1024 * 1024 + 1),
            headers={"Content-Type": "application/x-protobuf"},
        ).status_code
        == 413
    )
