import json
import pytest
from fastapi.testclient import TestClient
from agentscope.api import create_app
from agentscope.logs import decode_logs
from agentscope.store import Store
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
)


@pytest.fixture
def secured(tmp_path):
    app = create_app(str(tmp_path / "app.db"), auth_mode="required")
    keys = {}
    for tenant in ("one", "two"):
        app.state.identities.create_tenant(tenant)
        for role in ("collector", "viewer"):
            key = app.state.identities.issue(tenant, role, role)["api_key"]
            keys[tenant, role] = {"Authorization": "Bearer " + key}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client, app, keys


def payload():
    return {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [
                        {"key": "cloud.provider", "value": {"stringValue": "aws"}},
                        {"key": "tenant.id", "value": {"stringValue": "two"}},
                    ]
                },
                "scopeLogs": [
                    {
                        "logRecords": [
                            {
                                "timeUnixNano": "100",
                                "traceId": "01" * 16,
                                "spanId": "02" * 8,
                                "severityNumber": 17,
                                "body": {"stringValue": "secret customer prompt"},
                                "attributes": [
                                    {
                                        "key": "password",
                                        "value": {"stringValue": "sensitive"},
                                    }
                                ],
                            }
                        ]
                    }
                ],
            }
        ]
    }


def record(p):
    return p["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]


def test_auth_isolation_privacy_and_retry(secured):
    client, _, keys = secured
    assert client.post("/v1/logs", json=payload()).status_code == 401
    assert client.get("/api/logs").status_code == 401
    assert (
        client.post(
            "/v1/logs", json=payload(), headers=keys["one", "viewer"]
        ).status_code
        == 403
    )
    for _ in range(2):
        assert (
            client.post(
                "/v1/logs", json=payload(), headers=keys["one", "collector"]
            ).status_code
            == 200
        )
    assert client.get("/api/logs", headers=keys["one", "collector"]).status_code == 403
    result = client.get("/api/logs", headers=keys["one", "viewer"]).json()
    assert len(result["records"]) == 1
    assert result["records"][0]["resource"]["cloud.provider"] == "aws"
    assert "secret" not in json.dumps(result) and "sensitive" not in json.dumps(result)
    assert "tenant.id" not in json.dumps(result)
    assert (
        client.get("/api/logs", headers=keys["two", "viewer"]).json()["records"] == []
    )
    assert (
        client.get(
            "/api/logs?trace_id=" + "03" * 16, headers=keys["one", "viewer"]
        ).json()["records"]
        == []
    )
    assert (
        client.get("/api/logs?limit=501", headers=keys["one", "viewer"]).status_code
        == 422
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("traceId", "00" * 16),
        ("spanId", "01"),
        ("timeUnixNano", str(2**63)),
        ("severityNumber", 25),
    ],
)
def test_invalid_batch_is_atomic(secured, field, value):
    client, _, keys = secured
    p = payload()
    bad = dict(record(p))
    bad[field] = value
    p["resourceLogs"][0]["scopeLogs"][0]["logRecords"].append(bad)
    assert (
        client.post("/v1/logs", json=p, headers=keys["one", "collector"]).status_code
        == 400
    )
    assert (
        client.get("/api/logs", headers=keys["one", "viewer"]).json()["records"] == []
    )


def test_protobuf_and_limits(secured):
    client, _, keys = secured
    message = ExportLogsServiceRequest()
    log = message.resource_logs.add().scope_logs.add().log_records.add()
    log.observed_time_unix_nano = 42
    log.body.string_value = "omitted"
    headers = {**keys["one", "collector"], "Content-Type": "application/x-protobuf"}
    assert (
        client.post(
            "/v1/logs", content=message.SerializeToString(), headers=headers
        ).content
        == b""
    )
    assert (
        client.post(
            "/v1/logs", content=b"x" * (4 * 1024 * 1024 + 1), headers=headers
        ).status_code
        == 413
    )
    assert (
        client.post("/v1/logs", content=b"garbage", headers=headers).status_code == 400
    )
    assert (
        client.post(
            "/v1/logs", content=b"", headers={**headers, "Content-Encoding": "gzip"}
        ).status_code
        == 415
    )
    p = payload()
    p["resourceLogs"][0]["scopeLogs"][0]["logRecords"] = [record(p)] * 2001
    assert (
        client.post("/v1/logs", json=p, headers=keys["one", "collector"]).status_code
        == 400
    )


def test_capacity_rolls_back_and_retry_does_not_consume_capacity():
    store = Store(":memory:")
    rows = decode_logs(json.dumps(payload()).encode(), "application/json")
    store.ingest_logs(rows, capacity=1)
    store.ingest_logs(rows, capacity=1)
    p = payload()
    record(p)["timeUnixNano"] = "101"
    with pytest.raises(OverflowError):
        store.ingest_logs(
            decode_logs(json.dumps(p).encode(), "application/json"), capacity=1
        )
    assert store.logs() == rows
    store.close()


def test_unavailable_storage(secured, monkeypatch):
    client, app, keys = secured

    def fail(records):
        raise RuntimeError("private backend details")

    monkeypatch.setattr(app.state.tenants.get("one"), "ingest_logs", fail)
    response = client.post("/v1/logs", json=payload(), headers=keys["one", "collector"])
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert "private" not in response.text
