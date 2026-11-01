from concurrent.futures import ThreadPoolExecutor
import pytest
from pydantic import ValidationError
from agentscope.drift import analyze, demo_request, MetricWindow, ks_distance
from agentscope.guardian import Principal, ToolAction, submit, approve, execute_once
from agentscope.store import Store


@pytest.fixture
def store():
    db = Store(":memory:")
    yield db
    db.close()


def test_distance_known_values():
    assert ks_distance([1, 2, 3], [1, 2, 3]) == 0
    assert ks_distance([1, 2, 3], [4, 5, 6]) == 1


@pytest.mark.parametrize(
    "scenario,kind",
    [
        ("latency_spike", "operational"),
        ("quality_regression", "quality"),
        ("knowledge_aging", "retrieval"),
    ],
)
def test_seeded_shift_is_localized(store, scenario, kind):
    report = analyze(demo_request(scenario), store)
    assert [r["kind"] for r in report["rows"] if r["shift_detected"]] == [kind]
    assert all(r["adjusted_p_value"] >= r["p_value"] for r in report["rows"])


def test_stationary_fixture_has_no_alert(store):
    report = analyze(demo_request("stable"), store)
    assert report["alert_count"] == 0


def test_insufficient_and_nonfinite_samples_rejected():
    with pytest.raises(ValidationError):
        MetricWindow(
            name="latency", kind="operational", reference=[1] * 29, current=[1] * 30
        )
    with pytest.raises(ValidationError):
        MetricWindow(
            name="latency",
            kind="operational",
            reference=[float("nan")] * 30,
            current=[1] * 30,
        )


def test_denied_write_never_reaches_executor(store):
    event = submit(
        store,
        Principal("reader", "auditor"),
        ToolAction(tool="restart_worker", idempotency_key="deny-test-key"),
    )
    assert event["decision"] == "denied" and not event["executed"]
    assert store.db.execute("SELECT COUNT(*) FROM gateway_actions").fetchone()[0] == 0
    assert store.db.execute("SELECT count FROM gateway_resources").fetchone()[0] == 0
    with pytest.raises(ValueError):
        approve(store, event["id"])


def test_approval_executes_exactly_once_under_concurrency(store):
    event = submit(
        store,
        Principal("op", "operator"),
        ToolAction(tool="restart_worker", idempotency_key="approval-key"),
    )
    assert event["decision"] == "approval_required" and not event["executed"]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: approve(store, event["id"]), range(6)))
    assert all(r["executed"] for r in results)
    assert store.db.execute("SELECT count FROM gateway_resources").fetchone()[0] == 1


def test_idempotency_payload_collision_is_rejected(store):
    principal = Principal("op", "operator")
    execute_once(
        store,
        principal,
        ToolAction(tool="read_health", idempotency_key="collision-key"),
    )
    with pytest.raises(ValueError):
        execute_once(
            store,
            principal,
            ToolAction(tool="restart_worker", idempotency_key="collision-key"),
            approved=True,
        )
    assert store.db.execute("SELECT count FROM gateway_resources").fetchone()[0] == 0


def test_scope_and_export_denials(store):
    p = Principal("op", "operator")
    for tool, target in [
        ("read_health", "other-resource"),
        ("export_logs", "worker-alpha"),
    ]:
        event = submit(
            store,
            p,
            ToolAction(tool=tool, target=target, idempotency_key=tool + target),
        )
        assert event["decision"] == "denied" and not event["executed"]


def test_executor_enforces_policy_even_when_called_directly(store):
    with pytest.raises(ValueError):
        execute_once(
            store,
            Principal("reader", "auditor"),
            ToolAction(tool="restart_worker", idempotency_key="direct-call-key"),
            approved=True,
        )
    assert store.db.execute("SELECT count FROM gateway_resources").fetchone()[0] == 0


def test_gateway_http_approval_and_invalid_scenario(tmp_path):
    from fastapi.testclient import TestClient
    from agentscope.api import create_app

    with TestClient(
        create_app(str(tmp_path / "http.db")), base_url="http://127.0.0.1"
    ) as client:
        assert (
            client.post(
                "/api/guardian/demo", json={"scenario": "arbitrary_tool"}
            ).status_code
            == 422
        )
        denied = client.post(
            "/api/guardian/demo", json={"scenario": "unauthorized_write"}
        ).json()
        assert (
            client.post(f"/api/guardian/events/{denied['id']}/approve").status_code
            == 409
        )
        pending = client.post(
            "/api/guardian/demo", json={"scenario": "approval_required"}
        ).json()
        assert not pending["executed"]
        approved = client.post(f"/api/guardian/events/{pending['id']}/approve").json()
        repeated = client.post(f"/api/guardian/events/{pending['id']}/approve").json()
        assert (
            approved["result"]["restart_count"]
            == repeated["result"]["restart_count"]
            == 1
        )
