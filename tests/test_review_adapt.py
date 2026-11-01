import subprocess
import sys
import pytest
from agentscope.store import Store
from agentscope.demo import execute, RunRequest
from agentscope.review import review_trace
from agentscope.replay import replay_trace
from agentscope import adapt


@pytest.fixture
def store():
    db = Store(":memory:")
    yield db
    db.close()


async def test_panel_blocks_stale_evidence_without_majority_override(store):
    result = await execute(
        RunRequest(scenario="stale_evidence", variant="baseline"), store
    )
    report = review_trace(store, result["trace_id"])
    assert report["decision"] == "block" and report["disagreement"]
    assert {v["role"] for v in report["votes"] if v["verdict"] == "block"} == {
        "Reliability",
        "Evidence quality",
    }
    assert all(
        e["span_id"] in {s["span_id"] for s in store.spans(result["trace_id"])}
        for v in report["votes"]
        for e in v["evidence"]
    )


async def test_panel_failure_and_unsupported_evidence_abstain(store):
    result = await execute(RunRequest(scenario="healthy"), store)

    def broken(_):
        raise RuntimeError("Sensitive payload must not appear")

    def fabricated(_):
        return {"verdict": "pass", "evidence": [{"span_id": "fabricated"}]}

    report = review_trace(store, result["trace_id"], [broken, fabricated])
    assert report["decision"] == "abstain"
    assert "Sensitive payload" not in str(report)


async def test_recovered_timeout_does_not_claim_grounding(store):
    result = await execute(RunRequest(scenario="tool_timeout"), store)
    report = review_trace(store, result["trace_id"])
    assert (
        next(v for v in report["votes"] if v["role"] == "Evidence quality")["verdict"]
        == "abstain"
    )


async def test_retry_panel_uses_client_spans(store):
    result = await execute(RunRequest(scenario="retry_loop", variant="baseline"), store)
    report = review_trace(store, result["trace_id"])
    assert (
        next(v for v in report["votes"] if v["role"] == "Efficiency")["verdict"]
        == "review"
    )


async def test_builtin_replay_fixes_failure_and_rejects_unknown_trace(store):
    source = await execute(
        RunRequest(scenario="stale_evidence", variant="baseline"), store
    )
    case = await replay_trace(store, source["trace_id"])
    assert case["passed"] and case["replay_trace_id"] != source["trace_id"]
    with pytest.raises(ValueError):
        await replay_trace(store, "0" * 32)


async def test_bad_candidate_cannot_be_approved(store):
    p = await adapt.propose(store, "baseline-v1")
    assert not p["eligible"]
    with pytest.raises(ValueError):
        adapt.start_canary(store, p["id"])


async def test_canary_promotion_requires_samples_then_routes_new_version(store):
    p = await adapt.propose(store, "guarded-v2")
    current = adapt.start_canary(store, p["id"])
    assert current["candidate_percent"] == 20
    with pytest.raises(ValueError):
        adapt.promote(store)
    rows = await adapt.validation_batch(store)
    assert len(rows) == 10 and sum(r["route"] == "candidate" for r in rows) == 5
    assert all(r["passed"] for r in rows if r["route"] == "candidate")
    promoted = adapt.promote(store)
    assert promoted["stable"] == "guarded-v2" and not promoted["candidate"]
    assert adapt.route(promoted, "consistent-request") == "guarded-v2"
    assert adapt.rollback(store)["stable"] == "baseline-v1"
    with pytest.raises(ValueError):
        adapt.start_canary(store, p["id"])


async def test_injected_canary_failure_rolls_back_and_leaves_evidence(store):
    p = await adapt.propose(store, "guarded-v2")
    adapt.start_canary(store, p["id"])
    rows = await adapt.validation_batch(store, inject_outage=True)
    assert len(rows) == 1 and not rows[0]["passed"] and rows[0]["injected_outage"]
    assert store.spans(rows[0]["trace_id"])[0]["status"] == "ERROR"
    assert adapt.state(store)["candidate"] is None
    assert adapt.state(store)["stable"] == "baseline-v1"
    assert any(e["kind"] == "rolled_back" for e in store.list("adapt_events"))


async def test_stale_evaluation_cannot_replace_current_deployment(store):
    p1 = await adapt.propose(store, "guarded-v2")
    p2 = await adapt.propose(store, "guarded-v2")
    adapt.start_canary(store, p1["id"])
    adapt.rollback(store)
    with pytest.raises(ValueError, match="Deployment changed"):
        adapt.start_canary(store, p2["id"])


async def test_code_change_invalidates_evaluation(store, monkeypatch):
    p = await adapt.propose(store, "guarded-v2")
    monkeypatch.setattr(adapt, "digest", lambda _: "changed")
    with pytest.raises(ValueError, match="Code changed"):
        adapt.start_canary(store, p["id"])


def test_canary_assignment_is_stable_and_bounded():
    current = {
        "stable": "baseline-v1",
        "candidate": "guarded-v2",
        "candidate_percent": 20,
    }
    routes = [adapt.route(current, f"request-{i}") for i in range(1000)]
    assert routes == [adapt.route(current, f"request-{i}") for i in range(1000)]
    assert 150 < routes.count("guarded-v2") < 250


def test_cli_failure_returns_nonzero_and_writes_evidence(tmp_path):
    out = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agentscope.cli",
            "replay",
            "--scenario",
            "stale_evidence",
            "--variant",
            "baseline",
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1 and out.exists()
    assert '"passed": false' in result.stdout


def test_http_release_workflow_uses_server_evidence(tmp_path):
    from fastapi.testclient import TestClient
    from agentscope.api import create_app

    with TestClient(
        create_app(str(tmp_path / "releases.db")), base_url="http://127.0.0.1"
    ) as client:
        assert (
            client.post(
                "/api/adapt/proposals", json={"version": "guarded-v2", "eligible": True}
            ).status_code
            == 422
        )
        assert client.post("/api/adapt/promote").status_code == 409
        p = client.post("/api/adapt/proposals", json={"version": "guarded-v2"}).json()
        assert p["eligible"]
        assert client.post(f"/api/adapt/proposals/{p['id']}/approve").status_code == 200
        assert client.post("/api/adapt/promote").status_code == 409
        batch = client.post("/api/adapt/batch", json={"inject_outage": True}).json()
        assert batch[0]["injected_outage"]
        assert client.get("/api/adapt").json()["state"]["candidate"] is None
