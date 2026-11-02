import time
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from agentscope.store import Store
from agentscope.trace_drift import TraceWindows, compare
from agentscope.api import create_app

END = int(time.time()) - 60


def window():
    return TraceWindows(
        service="test-agent",
        reference_start=END - 7200,
        reference_end=END - 3600,
        current_start=END - 3600,
        current_end=END,
    )


def spans(index, start, current=False, usage=True):
    trace = f"{index:032x}"

    def s(sid, parent, name, attrs, kind=1):
        return {
            "trace_id": trace,
            "span_id": f"{sid:016x}",
            "parent_id": f"{parent:016x}" if parent else None,
            "name": name,
            "start_ns": int(start * 1e9),
            "end_ns": int((start + (0.5 if current else 0.1)) * 1e9),
            "status": "ERROR" if current and sid == 2 else "OK",
            "kind": kind,
            "attributes": attrs,
            "resource": {"service.name": "test-agent"},
            "events": [],
            "links": [],
        }

    return [
        s(1, None, "run", {}),
        s(
            2,
            1,
            "tool",
            {"tool.name": "lookup", "tool.attempt": 2 if current else 1},
            3,
        ),
        s(
            3,
            1,
            "model",
            {
                "gen_ai.request.model": "fixture",
                **(
                    {
                        "gen_ai.usage.input_tokens": 200 if current else 100,
                        "gen_ai.usage.output_tokens": 50,
                    }
                    if usage
                    else {}
                ),
            },
            3,
        ),
    ]


@pytest.fixture
def store():
    s = Store(":memory:")
    for i in range(30):
        s.ingest(spans(i + 1, END - 7000 + i))
        s.ingest(spans(i + 101, END - 3400 + i, True))
    yield s
    s.close()


def test_shift_and_exact_evidence(store):
    report = compare(window(), store)
    assert report["alert_count"] == 4
    for row in report["rows"]:
        assert row["status"] == "tested"
        assert row["n_reference"] == row["n_current"] == 30
        assert row["ks_distance"] == 1
        assert row["adjusted_p_value"] < 0.05
        for item in row["reference_evidence"]:
            assert store.spans(item["trace_id"])
    assert store.get("drift_reports", report["id"])["windows"] == window().model_dump()


def test_missing_usage_not_zero_and_partial_excluded(store):
    for i in range(30):
        store.ingest(spans(i + 101, END - 3400 + i, True, False))
    partial = spans(999, END - 3200)
    partial[1]["parent_id"] = "f" * 16
    store.ingest(partial)
    report = compare(window(), store)
    tokens = next(r for r in report["rows"] if r["key"] == "tokens")
    assert tokens["status"] == "insufficient" and tokens["n_current"] == 0
    assert tokens["missing_current"] == 30
    assert report["coverage"]["current"]["excluded_trace_ids"] == [f"{999:032x}"]


def test_no_data_is_not_healthy():
    s = Store(":memory:")
    report = compare(window(), s)
    assert all(r["status"] == "insufficient" for r in report["rows"])
    s.close()


def test_window_cap_and_service_filter(store):
    for i in range(31, 258):
        store.ingest(spans(i + 1000, END - 7000 + i))
    with pytest.raises(ValueError, match="256"):
        compare(window(), store)
    w = window().model_copy(update={"service": "absent"})
    assert compare(w, store)["coverage"]["reference"]["root_candidates"] == 0


def test_half_open_end_and_unfinished_trace(store):
    store.ingest(spans(998, END - 3600))
    unfinished = spans(999, END - 1)
    unfinished[0]["end_ns"] = int((END + 10) * 1e9)
    store.ingest(unfinished)
    r = compare(window(), store)
    assert r["coverage"]["reference"]["root_candidates"] == 30
    assert r["coverage"]["current"]["eligible_traces"] == 31
    assert f"{999:032x}" in r["coverage"]["current"]["excluded_trace_ids"]


def test_server_tool_span_not_double_counted(store):
    extra = spans(1, END - 7000)[1]
    extra["span_id"] = "f" * 16
    extra["kind"] = 2
    extra["status"] = "ERROR"
    store.ingest([extra])
    r = compare(window(), store)
    row = next(x for x in r["rows"] if x["key"] == "tool_error_rate")
    assert row["reference_mean"] == 0


@pytest.mark.parametrize(
    "change",
    [
        {"reference_end": END},
        {"current_end": time.time() + 100},
        {"reference_start": END - 40 * 86400},
    ],
)
def test_bad_windows(change):
    with pytest.raises(ValidationError):
        TraceWindows(**{**window().model_dump(), **change})


def test_tenant_and_role_boundaries(tmp_path):
    app = create_app(str(tmp_path / "app.db"))
    identities = app.state.identities
    for tenant in ["a", "b"]:
        identities.create_tenant(tenant)
    a = identities.issue("a", "operator-a", "operator")["api_key"]
    b = identities.issue("b", "operator-b", "operator")["api_key"]
    viewer = identities.issue("a", "viewer-a", "viewer")["api_key"]
    s = app.state.tenants.get("a")
    for i in range(30):
        s.ingest(spans(i + 1, END - 7000 + i))
        s.ingest(spans(i + 101, END - 3400 + i, True))
    with TestClient(app, base_url="http://localhost") as client:

        def run(key):
            return client.post(
                "/api/drift/traces",
                json=window().model_dump(),
                headers={"Authorization": "Bearer " + key, "X-Tenant-ID": "a"},
            )

        assert run(viewer).status_code == 403
        assert (
            client.post("/api/drift/traces", json=window().model_dump()).status_code
            == 401
        )
        assert run(a).json()["alert_count"] == 4
        report = run(b).json()
        assert all(r["status"] == "insufficient" for r in report["rows"])
        assert (
            len(
                client.get(
                    "/api/drift/reports", headers={"Authorization": "Bearer " + b}
                ).json()
            )
            == 1
        )


def test_invalid_tokens_and_unknown_attempts_are_missing(store):
    for i in range(30):
        rows = spans(i + 101, END - 3400 + i, True)
        rows[1]["attributes"].pop("tool.attempt")
        rows[2]["attributes"]["gen_ai.usage.input_tokens"] = -1
        store.ingest(rows)
    r = compare(window(), store)
    for key in ["tokens", "retries"]:
        row = next(x for x in r["rows"] if x["key"] == key)
        assert row["status"] == "insufficient"
        assert row["missing_current"] == 30


def test_stationary_collected_windows_do_not_alert(store):
    for i in range(30):
        store.ingest(spans(i + 101, END - 3400 + i))
    r = compare(window(), store)
    assert r["alert_count"] == 0
    assert all(x["status"] == "tested" and x["ks_distance"] == 0 for x in r["rows"])
