import os
import sqlite3
import subprocess
import sys
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceResponse,
)
from opentelemetry.sdk.trace.export import SpanExportResult

from agentscope.api import create_app
from agentscope.delivery import DurableDelivery, QueueFull
from agentscope.telemetry import create_tracer
from test_core import request_fixture

URL = "http://localhost/v1/traces"


def queue(tmp_path, handler, **kwargs):
    return DurableDelivery(
        tmp_path / "outbox.db",
        URL,
        "private-credential",
        start_worker=False,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def ready(q):
    with q.lock, q.db:
        q.db.execute("UPDATE batches SET due=0")


def test_recovery_after_abrupt_process_exit(tmp_path):
    path = tmp_path / "outbox.db"
    script = """
import os,sys
from agentscope.delivery import DurableDelivery
q=DurableDelivery(sys.argv[1], 'http://localhost/v1/traces', 'private-credential',start_worker=False)
q.enqueue(b'persisted')
os._exit(0)
"""
    subprocess.run([sys.executable, "-c", script, str(path)], check=True)
    seen = []
    q = queue(tmp_path, lambda r: seen.append(r.content) or httpx.Response(200))
    try:
        assert q.status()["pending"] == 1
        assert q.deliver_once()
        assert seen == [b"persisted"]
        assert q.status()["counters"]["delivered"] == 1
    finally:
        q.close()


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_retryable_status_persists_backoff(tmp_path, status):
    q = queue(
        tmp_path, lambda r: httpx.Response(status, headers={"Retry-After": "120"})
    )
    try:
        q.enqueue(b"x")
        q.deliver_once()
        row = q.db.execute("SELECT * FROM batches").fetchone()
        assert row["due"] > time.time() + 110
        assert row["attempts"] == 1
        assert not q.deliver_once()
        assert q.status()["pending"] == 1
    finally:
        q.close()


@pytest.mark.parametrize("status", [400, 401, 403, 413, 500, 302])
def test_permanent_failure_quarantines_without_retry_or_error_text(tmp_path, status):
    q = queue(tmp_path, lambda r: httpx.Response(status, text="secret server response"))
    try:
        q.enqueue(b"x")
        q.deliver_once()
        assert q.status()["quarantined"] == 1
        assert not q.flush(0)
        assert not q.deliver_once()
        assert (
            q.db.execute("SELECT reason FROM batches").fetchone()[0] == f"http_{status}"
        )
    finally:
        q.close()


def test_ack_loss_retries_without_duplicate_spans(tmp_path):
    app = create_app(str(tmp_path / "collector.db"), auth_mode="development")
    calls = []
    with TestClient(app, base_url="http://localhost") as client:

        def handler(request):
            response = client.post(
                "/v1/traces",
                content=request.content,
                headers={"Content-Type": "application/x-protobuf"},
            )
            assert response.status_code == 200
            calls.append(1)
            if len(calls) == 1:
                raise httpx.ReadTimeout("lost ack")
            return httpx.Response(200)

        q = queue(tmp_path, handler)
        try:
            q.enqueue(request_fixture().SerializeToString())
            q.deliver_once()
            assert q.status()["pending"] == 1
            ready(q)
            q.deliver_once()
            assert q.status()["pending"] == 0
            assert len(calls) == 2
            assert (
                app.state.store.db.execute("SELECT COUNT(*) FROM spans").fetchone()[0]
                == 2
            )
        finally:
            q.close()


def test_capacity_includes_quarantine_and_never_evicts(tmp_path):
    q = queue(tmp_path, lambda r: httpx.Response(401), max_batches=2, max_bytes=3)
    try:
        q.enqueue(b"abc")
        q.deliver_once()
        with pytest.raises(QueueFull):
            q.enqueue(b"d")
        assert q.status()["payload_bytes"] == 3
        assert q.status()["counters"]["rejected"] == 1
        assert q.db.execute("SELECT payload FROM batches").fetchone()[0] == b"abc"
    finally:
        q.close()


def test_batch_capacity_and_released_space(tmp_path):
    q = queue(tmp_path, lambda r: httpx.Response(200), max_batches=1)
    try:
        q.enqueue(b"a")
        with pytest.raises(QueueFull):
            q.enqueue(b"b")
        q.deliver_once()
        q.enqueue(b"b")
        assert q.status()["pending"] == 1
    finally:
        q.close()


def test_owner_and_destination_binding(tmp_path):
    q = queue(tmp_path, lambda r: httpx.Response(200))
    with pytest.raises(ValueError, match="owner"):
        queue(tmp_path, lambda r: httpx.Response(200))
    q.close()
    for endpoint, key in [
        (URL, "different-tenant-key"),
        ("http://localhost/other", "private-credential"),
    ]:
        with pytest.raises(ValueError, match="different endpoint or credential"):
            DurableDelivery(tmp_path / "outbox.db", endpoint, key)
    assert os.stat(tmp_path / "outbox.db").st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "body",
    [
        b"not protobuf",
        ExportTraceServiceResponse(
            partial_success={"rejected_spans": 1, "error_message": "sensitive message"}
        ).SerializeToString(),
    ],
)
def test_invalid_and_partial_success_not_silently_acknowledged(tmp_path, body):
    q = queue(tmp_path, lambda r: httpx.Response(200, content=body))
    try:
        q.enqueue(b"x")
        q.deliver_once()
        assert q.status()["quarantined"] == 1
        assert not q.deliver_once()
    finally:
        q.close()


def test_exporter_redacts_before_disk_and_rejects_after_shutdown(tmp_path):
    path = tmp_path / "private.db"
    tracer, provider, exporter = create_tracer(
        endpoint="http://127.0.0.1:1/v1/traces",
        export_token="credential-must-not-persist",
        outbox_path=path,
    )
    with tracer.start_as_current_span("safe-name") as span:
        span.set_attribute("input.value", "raw-private-prompt")
    assert not exporter.force_flush(20)
    assert exporter.delivery.status()["pending"] == 1
    provider.shutdown()
    with sqlite3.connect(path) as db:
        raw = db.execute("SELECT payload FROM batches").fetchone()[0]
        assert b"raw-private-prompt" not in raw
    assert b"credential-must-not-persist" not in path.read_bytes()
    assert exporter.export([]) == SpanExportResult.FAILURE


def test_background_flush_and_shutdown(tmp_path):
    seen = []
    q = DurableDelivery(
        tmp_path / "outbox.db",
        URL,
        transport=httpx.MockTransport(
            lambda r: seen.append(r.content) or httpx.Response(200)
        ),
    )
    q.enqueue(b"x")
    assert q.flush(2000)
    assert seen == [b"x"]
    q.close()
    q.close()


def test_collector_storage_failure_returns_retryable_503(tmp_path, monkeypatch):
    app = create_app(str(tmp_path / "api.db"), auth_mode="development")
    with TestClient(app, base_url="http://localhost") as client:

        def fail(spans):
            raise sqlite3.OperationalError("private filesystem path")

        monkeypatch.setattr(app.state.store, "ingest", fail)
        response = client.post(
            "/v1/traces",
            content=request_fixture().SerializeToString(),
            headers={"Content-Type": "application/x-protobuf"},
        )
        assert response.status_code == 503
        assert response.headers["retry-after"] == "1"
        assert "private" not in response.text
        invalid = client.post(
            "/v1/traces",
            content=b"invalid",
            headers={"Content-Type": "application/x-protobuf"},
        )
        assert invalid.status_code == 400


def test_real_http_outage_recovery(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    recovered = threading.Event()
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            if recovered.is_set():
                received.append(body)
            self.send_response(200 if recovered.is_set() else 503)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    path = tmp_path / "http-outbox.db"
    endpoint = f"http://127.0.0.1:{server.server_port}/v1/traces"
    q = DurableDelivery(path, endpoint, start_worker=False)
    try:
        q.enqueue(request_fixture().SerializeToString())
        q.deliver_once()
        assert q.status()["pending"] == 1
        q.close()
        recovered.set()
        q = DurableDelivery(path, endpoint)
        assert q.flush(5000)
        assert len(received) == 1
    finally:
        q.close()
        server.shutdown()
        server.server_close()
        thread.join()
