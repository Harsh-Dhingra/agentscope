"""Exercise a real API server, MCP stdio worker, and OTLP HTTP callback."""

import os
import socket
import subprocess
import sys
import time
import httpx
from agentscope.identity import IdentityStore


def test_distributed_mcp_trace(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "AGENTSCOPE_DB": str(tmp_path / "smoke.db"),
        "AGENTSCOPE_DEMO_EXPORT_ENDPOINT": base + "/v1/traces",
    }
    identity = IdentityStore(tmp_path / "identity.db")
    identity.create_tenant("local")
    credential = identity.issue("local", "integration-operator", "operator")
    env["AGENTSCOPE_AUTH_MODE"] = "required"
    env["AGENTSCOPE_IDENTITY_DB"] = str(tmp_path / "identity.db")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "agentscope.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with httpx.Client(
            timeout=25,
            trust_env=False,
            headers={"Authorization": "Bearer " + credential["api_key"]},
        ) as client:
            for _ in range(100):
                try:
                    if client.get(base + "/api/health").status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("Test server failed to start")
            response = client.post(
                base + "/api/runs",
                json={
                    "scenario": "healthy",
                    "variant": "guarded",
                    "runtime": "scripted",
                    "transport": "mcp",
                },
            )
            response.raise_for_status()
            run = response.json()
            assert run["passed"]
            spans = client.get(base + "/api/traces/" + run["trace_id"]).json()["spans"]
            assert {s["resource"]["service.name"] for s in spans} == {
                "incident-agent",
                "mcp-runbook-worker",
            }
            worker = next(s for s in spans if s["name"] == "mcp.lookup_runbook")
            caller = next(s for s in spans if s["name"] == "tool.lookup_runbook")
            assert worker["parent_id"] == caller["span_id"]
            assert worker["trace_id"] == caller["trace_id"]
            assert (
                identity.db.execute(
                    "SELECT COUNT(*) FROM credentials WHERE role='collector' AND revoked=1"
                ).fetchone()[0]
                == 1
            )
    finally:
        identity.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
