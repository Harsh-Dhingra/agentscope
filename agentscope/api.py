import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from google.protobuf.json_format import ParseDict
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from .store import Store
from .telemetry import decode_otlp
from .analysis import diagnose, summarize
from .demo import RunRequest, execute, experiment, SCENARIOS
from .drift import DriftRequest, analyze, demo_request
from .guardian import demo_action, approve
from pydantic import BaseModel, ConfigDict, Field
from .review import review_trace
from .replay import replay_trace
from . import adapt
from typing import Literal

MAX_BODY = 4 * 1024 * 1024


class DriftDemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Literal[
        "stable", "latency_spike", "quality_regression", "knowledge_aging"
    ] = "latency_spike"


class GuardianDemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Literal[
        "allowed_read", "unauthorized_write", "approval_required", "blocked_export"
    ] = "unauthorized_write"


class TraceReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trace_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class ReplayRequest(TraceReviewRequest):
    variant: Literal["baseline", "guarded"] = "guarded"


class ProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal["baseline-v1", "guarded-v2"] = "guarded-v2"


class ValidationBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inject_outage: bool = False


class RoutedRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Literal["healthy", "stale_evidence", "tool_timeout", "retry_loop"] = (
        "healthy"
    )
    request_id: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_:-]+$")


def create_app(db_path=None):
    store = Store(db_path or os.environ.get("AGENTSCOPE_DB", "data/agentscope.db"))

    @asynccontextmanager
    async def lifespan(app):
        yield
        store.close()

    app = FastAPI(title="AgentScope", version="0.3.0", lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"]
    )
    app.state.store = store
    app.state.run_lock = asyncio.Lock()

    @app.middleware("http")
    async def local_origin(request, call_next):
        # No permissive CORS. Block browser-origin writes from unrelated sites.
        origin = request.headers.get("origin")
        if origin and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            from urllib.parse import urlparse

            allowed = {"127.0.0.1", "localhost", "::1"}
            if urlparse(origin).hostname not in allowed:
                return Response("Origin not allowed", status_code=403)
        return await call_next(request)

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "version": "0.3.0",
            "storage": "sqlite",
            "scope": "local development; no user authentication",
        }

    @app.get("/api/scenarios")
    def scenarios():
        return SCENARIOS

    @app.post("/v1/traces")
    async def ingest(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY:
                raise HTTPException(413, "OTLP body exceeds 4 MiB")
        content_type = request.headers.get("content-type", "").split(";")[0]
        try:
            message = ExportTraceServiceRequest()
            if content_type == "application/x-protobuf":
                message.ParseFromString(bytes(body))
            elif content_type == "application/json":
                # OTLP JSON uses hex IDs; protobuf JSON uses base64 for bytes.
                import base64

                payload = json.loads(body)
                for resource in payload.get("resourceSpans", []):
                    for scope in resource.get("scopeSpans", []):
                        for span in scope.get("spans", []):
                            for obj in [span, *span.get("links", [])]:
                                for key in ["traceId", "spanId", "parentSpanId"]:
                                    if obj.get(key):
                                        obj[key] = base64.b64encode(
                                            bytes.fromhex(obj[key])
                                        ).decode()
                ParseDict(payload, message)
            else:
                raise HTTPException(415, "Use OTLP HTTP protobuf or JSON")
            spans = decode_otlp(message)
            store.ingest(spans)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, "Invalid OTLP payload")
        return Response(
            content=b"" if content_type == "application/x-protobuf" else b"{}",
            media_type=content_type,
        )

    @app.get("/api/traces")
    def traces():
        return [summarize(store.spans(t)) for t in store.trace_ids()]

    @app.get("/api/traces/{trace_id}")
    def trace(trace_id: str):
        spans = store.spans(trace_id)
        if not spans:
            raise HTTPException(404, "Trace not found")
        run = next((r for r in store.list("runs") if r["trace_id"] == trace_id), None)
        return {
            "summary": summarize(spans),
            "spans": spans,
            "findings": diagnose(spans),
            "run": run,
        }

    @app.get("/api/runs")
    def runs():
        return store.list("runs")

    @app.post("/api/runs")
    async def run(request: RunRequest):
        if app.state.run_lock.locked():
            raise HTTPException(409, "Another workload is running")
        async with app.state.run_lock:
            return await execute(request, store)

    @app.get("/api/experiments")
    def experiments():
        return store.list("experiments", 20)

    @app.post("/api/experiments")
    async def evaluate():
        if app.state.run_lock.locked():
            raise HTTPException(409, "Another workload is running")
        async with app.state.run_lock:
            return await experiment(store)

    @app.get("/api/drift/reports")
    def drift_reports():
        return store.list("drift_reports", 30)

    @app.post("/api/drift/analyze")
    def drift_analyze(request: DriftRequest):
        return analyze(request, store)

    @app.post("/api/drift/demo")
    def drift_demo(request: DriftDemoRequest):
        return analyze(
            demo_request(request.scenario), store, source="synthetic seeded windows"
        )

    @app.get("/api/guardian/events")
    def guardian_events():
        return store.list("policy_events")

    @app.post("/api/guardian/demo")
    def guardian_demo(request: GuardianDemoRequest):
        return demo_action(store, request.scenario)

    @app.post("/api/guardian/events/{event_id}/approve")
    def guardian_approve(event_id: str):
        try:
            return approve(store, event_id)
        except KeyError:
            raise HTTPException(404, "Action not found")
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.get("/api/reviews")
    def reviews():
        return store.list("review_reports", 30)

    @app.post("/api/reviews")
    def review(request: TraceReviewRequest):
        try:
            return review_trace(store, request.trace_id)
        except KeyError:
            raise HTTPException(404, "Trace not found")

    @app.get("/api/replays")
    def replays():
        return store.list("replay_cases", 30)

    @app.post("/api/replays")
    async def replay(request: ReplayRequest):
        if app.state.run_lock.locked():
            raise HTTPException(409, "Another workload is running")
        async with app.state.run_lock:
            try:
                return await replay_trace(store, request.trace_id, request.variant)
            except ValueError as exc:
                raise HTTPException(409, str(exc))

    @app.get("/api/adapt")
    def adaptation():
        return adapt.overview(store)

    @app.post("/api/adapt/proposals")
    async def proposal(request: ProposalRequest):
        if app.state.run_lock.locked():
            raise HTTPException(409, "Another workload is running")
        async with app.state.run_lock:
            return await adapt.propose(store, request.version)

    @app.post("/api/adapt/proposals/{proposal_id}/approve")
    async def approve_proposal(proposal_id: str):
        if app.state.run_lock.locked():
            raise HTTPException(409, "Wait for the workload to complete")
        async with app.state.run_lock:
            try:
                return adapt.start_canary(store, proposal_id)
            except KeyError:
                raise HTTPException(404, "Proposal not found")
            except ValueError as exc:
                raise HTTPException(409, str(exc))

    @app.post("/api/adapt/batch")
    async def batch(request: ValidationBatchRequest):
        if app.state.run_lock.locked():
            raise HTTPException(409, "Another workload is running")
        async with app.state.run_lock:
            try:
                return await adapt.validation_batch(store, request.inject_outage)
            except ValueError as exc:
                raise HTTPException(409, str(exc))

    @app.post("/api/adapt/run")
    async def routed_run(request: RoutedRunRequest):
        if app.state.run_lock.locked():
            raise HTTPException(409, "Another workload is running")
        async with app.state.run_lock:
            return await adapt.run_routed(store, request.scenario, request.request_id)

    @app.post("/api/adapt/{action}")
    async def transition(action: Literal["promote", "rollback"]):
        if app.state.run_lock.locked():
            raise HTTPException(409, "Wait for the workload to complete")
        async with app.state.run_lock:
            try:
                return (
                    adapt.promote(store)
                    if action == "promote"
                    else adapt.rollback(store)
                )
            except ValueError as exc:
                raise HTTPException(409, str(exc))

    dist = Path(__file__).resolve().parent.parent / "web" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="dashboard")
    return app


app = create_app()
