import json
import os
import subprocess
import sys
import pytest
from fastapi.testclient import TestClient
from agentscope.api import create_app
from agentscope.identity import IdentityStore
from agentscope.access import TenantStores
from agentscope.telemetry import SafeExporter


@pytest.fixture
def secured(tmp_path):
    app = create_app(str(tmp_path / "app.db"), auth_mode="required")
    keys = {}
    for tenant in ("local", "acme", "ACME"):
        app.state.identities.create_tenant(tenant)
        keys[tenant] = {
            role: app.state.identities.issue(tenant, f"person-{role}", role)
            for role in ("viewer", "operator", "reviewer", "collector")
        }
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client, app, keys


def headers(key):
    return {"Authorization": "Bearer " + key["api_key"]}


def otlp(name):
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "tenant.id", "value": {"stringValue": "acme"}}
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "01" * 16,
                                "spanId": "02" * 8,
                                "name": name,
                                "startTimeUnixNano": "100",
                                "endTimeUnixNano": "200",
                            }
                        ]
                    }
                ],
            }
        ]
    }


@pytest.mark.parametrize(
    "path",
    [
        "/api/traces",
        "/api/runs",
        "/api/experiments",
        "/api/drift/reports",
        "/api/guardian/events",
        "/api/reviews",
        "/api/replays",
        "/api/adapt",
        "/api/access/audit",
    ],
)
def test_anonymous_data_access_is_rejected(secured, path):
    client, _, _ = secured
    assert client.get(path).status_code == 401
    assert client.get("/api/health").json()["authentication"] == "required"


@pytest.mark.parametrize(
    "path",
    [
        "/api/runs",
        "/api/experiments",
        "/api/drift/demo",
        "/api/guardian/demo",
        "/api/reviews",
        "/api/replays",
        "/api/adapt/proposals",
        "/api/adapt/batch",
        "/api/adapt/promote",
        "/api/adapt/rollback",
    ],
)
def test_viewer_cannot_mutate(secured, path):
    client, _, keys = secured
    assert (
        client.post(path, json={}, headers=headers(keys["local"]["viewer"])).status_code
        == 403
    )


def test_tenant_binding_and_same_trace_ids_are_isolated(secured):
    client, app, keys = secured
    for tenant in ("local", "acme"):
        assert (
            client.post(
                "/v1/traces",
                json=otlp(tenant),
                headers={**headers(keys[tenant]["collector"]), "X-Tenant-ID": "acme"},
            ).status_code
            == 200
        )
    for tenant in ("local", "acme"):
        response = client.get(
            "/api/traces/" + "01" * 16,
            headers={**headers(keys[tenant]["viewer"]), "X-Tenant-ID": "local"},
        )
        assert response.json()["summary"]["name"] == tenant
        assert "tenant.id" not in response.json()["spans"][0]["resource"]
    assert (
        client.get(
            "/api/traces/" + "01" * 16, headers=headers(keys["ACME"]["viewer"])
        ).status_code
        == 404
    )
    # Case-distinct tenants must not alias files on case-insensitive filesystems.
    assert (
        app.state.tenants.get("acme").db.execute("PRAGMA database_list").fetchone()[2]
        != app.state.tenants.get("ACME")
        .db.execute("PRAGMA database_list")
        .fetchone()[2]
    )


def test_collector_is_ingest_only_and_cannot_login(secured):
    client, _, keys = secured
    key = keys["local"]["collector"]
    assert (
        client.post(
            "/v1/traces", json=otlp("collected"), headers=headers(key)
        ).status_code
        == 200
    )
    assert client.get("/api/traces", headers=headers(key)).status_code == 403
    assert client.post("/api/runs", json={}, headers=headers(key)).status_code == 403
    assert (
        client.post("/api/auth/login", json={"api_key": key["api_key"]}).status_code
        == 401
    )


def test_separate_reviewer_and_cross_tenant_approval(secured):
    client, app, keys = secured
    event = client.post(
        "/api/guardian/demo",
        json={"scenario": "approval_required"},
        headers=headers(keys["local"]["operator"]),
    ).json()
    path = f"/api/guardian/events/{event['id']}/approve"
    assert (
        client.post(path, headers=headers(keys["local"]["operator"])).status_code == 403
    )
    assert (
        client.post(path, headers=headers(keys["acme"]["reviewer"])).status_code == 404
    )
    same_person = app.state.identities.issue("local", "person-operator", "reviewer")
    assert client.post(path, headers=headers(same_person)).status_code == 403
    response = client.post(path, headers=headers(keys["local"]["reviewer"]))
    assert (
        response.status_code == 200 and response.json()["result"]["restart_count"] == 1
    )
    assert response.json()["approved_by"] == "person-reviewer"
    second_reviewer = app.state.identities.issue(
        "local", "another-reviewer", "reviewer"
    )
    replay = client.post(path, headers=headers(second_reviewer)).json()
    assert (
        replay["approved_by"] == "person-reviewer"
        and replay["result"]["restart_count"] == 1
    )
    assert (
        app.state.tenants.get("acme")
        .db.execute("SELECT count FROM gateway_resources")
        .fetchone()[0]
        == 0
    )


def test_release_proposer_cannot_self_approve_and_state_is_isolated(secured):
    client, app, keys = secured
    p = client.post(
        "/api/adapt/proposals",
        json={"version": "guarded-v2"},
        headers=headers(keys["local"]["operator"]),
    ).json()
    assert p["created_by"] == "person-operator"
    path = f"/api/adapt/proposals/{p['id']}/approve"
    same_person = app.state.identities.issue("local", "person-operator", "reviewer")
    assert client.post(path, headers=headers(same_person)).status_code == 403
    assert (
        client.post(path, headers=headers(keys["acme"]["reviewer"])).status_code == 404
    )
    assert (
        client.post(path, headers=headers(keys["local"]["reviewer"])).status_code == 200
    )
    assert (
        client.get("/api/adapt", headers=headers(keys["acme"]["viewer"])).json()[
            "state"
        ]["candidate"]
        is None
    )
    assert (
        client.post(
            "/api/adapt/batch", json={}, headers=headers(keys["local"]["reviewer"])
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/adapt/batch", json={}, headers=headers(keys["local"]["operator"])
        ).status_code
        == 200
    )
    assert (
        client.post("/api/adapt/promote", headers=headers(same_person)).status_code
        == 403
    )
    assert (
        client.post(
            "/api/adapt/promote", headers=headers(keys["local"]["reviewer"])
        ).status_code
        == 200
    )


def test_browser_session_csrf_origin_logout_and_rotation(secured):
    client, _, keys = secured
    login = client.post(
        "/api/auth/login", json={"api_key": keys["local"]["operator"]["api_key"]}
    )
    assert login.status_code == 200
    cookie = login.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert keys["local"]["operator"]["api_key"] not in login.text
    csrf = login.json()["csrf_token"]
    assert client.get("/api/traces").status_code == 200
    assert client.post("/api/guardian/demo", json={}).status_code == 403
    assert (
        client.post(
            "/api/guardian/demo", json={}, headers={"X-CSRF-Token": "wrong"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/guardian/demo",
            json={},
            headers={"X-CSRF-Token": csrf, "Origin": "http://127.0.0.1:9999"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/guardian/demo",
            json={},
            headers={"X-CSRF-Token": csrf, "Origin": "http://127.0.0.1"},
        ).status_code
        == 200
    )
    old = client.cookies.get("agentscope_session")
    relogin = client.post(
        "/api/auth/login", json={"api_key": keys["local"]["operator"]["api_key"]}
    )
    assert client.cookies.get("agentscope_session") != old
    assert (
        client.post(
            "/api/auth/logout",
            json={},
            headers={"X-CSRF-Token": relogin.json()["csrf_token"]},
        ).status_code
        == 200
    )
    assert client.get("/api/traces").status_code == 401


def test_revocation_and_expiry_invalidate_bearer_and_session(secured):
    client, app, keys = secured
    key = keys["local"]["operator"]
    assert (
        client.post("/api/auth/login", json={"api_key": key["api_key"]}).status_code
        == 200
    )
    app.state.identities.revoke(key["key_id"])
    assert client.get("/api/traces").status_code == 401
    assert client.get("/api/traces", headers=headers(key)).status_code == 401
    expired = keys["local"]["viewer"]
    with app.state.identities.db:
        app.state.identities.db.execute(
            "UPDATE credentials SET expires=0 WHERE id=?", (expired["key_id"],)
        )
    assert client.get("/api/traces", headers=headers(expired)).status_code == 401


def test_expired_session_does_not_fall_back_to_development(secured):
    client, app, keys = secured
    client.post("/api/auth/login", json={"api_key": keys["local"]["viewer"]["api_key"]})
    with app.state.identities.db:
        app.state.identities.db.execute("UPDATE sessions SET expires=0")
    assert client.get("/api/traces").status_code == 401
    assert client.get("/api/auth/session").json()["authenticated"] is False


def test_audit_is_scoped_and_excludes_secrets(secured):
    client, _, keys = secured
    client.post(
        "/api/guardian/demo", json={}, headers=headers(keys["local"]["operator"])
    )
    client.post(
        "/api/runs",
        json={"private": "do-not-log"},
        headers=headers(keys["local"]["viewer"]),
    )
    events = client.get(
        "/api/access/audit", headers=headers(keys["local"]["viewer"])
    ).json()
    assert {e["status"] for e in events} == {200, 403}
    assert all(e["tenant"] == "local" for e in events)
    assert "do-not-log" not in json.dumps(events) and keys["local"]["operator"][
        "api_key"
    ] not in json.dumps(events)
    assert (
        client.get("/api/access/audit", headers=headers(keys["acme"]["viewer"])).json()
        == []
    )


def test_login_validation_does_not_echo_credentials_and_is_throttled(secured):
    client, _, _ = secured
    response = client.post("/api/auth/login", json={"api_key": "secret-short"})
    assert response.status_code == 422 and "secret-short" not in response.text
    for _ in range(20):
        assert (
            client.post(
                "/api/auth/login", json={"api_key": "as_" + "0" * 43}
            ).status_code
            == 401
        )
    assert (
        client.post("/api/auth/login", json={"api_key": "as_" + "0" * 43}).status_code
        == 429
    )


def test_credential_cli_writes_private_file_and_hashes_only(tmp_path):
    path = tmp_path / "identity.db"
    out = tmp_path / "keys.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "agentscope.identity",
            "--db",
            str(path),
            "init",
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    keys = json.loads(out.read_text())["credentials"]
    assert len(keys) == 4 and (os.stat(out).st_mode & 0o077) == 0
    assert all(k["api_key"] not in proc.stdout for k in keys)
    db = IdentityStore(path)
    try:
        rows = [dict(row) for row in db.db.execute("SELECT * FROM credentials")]
        assert all(k["api_key"] not in json.dumps(rows) for k in keys)
        assert db.authenticate(keys[0]["api_key"])["tenant"] == "local"
    finally:
        db.close()


def test_tenant_paths_and_remote_credentials_fail_closed(tmp_path):
    tenants = TenantStores(str(tmp_path / "local.db"))
    with pytest.raises(ValueError):
        tenants.get("../another")
    with pytest.raises(ValueError, match="HTTPS"):
        SafeExporter(
            endpoint="http://example.com/v1/traces",
            allow_remote=True,
            export_token="secret",
        )
    with pytest.raises(ValueError, match="authentication mode"):
        create_app(str(tmp_path / "bad.db"), auth_mode="requird")
