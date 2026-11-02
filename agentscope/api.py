import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from google.protobuf.json_format import ParseDict
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from .store import Store
from .identity import IdentityStore
from .access import (
    TenantStores,
    tenant_store,
    install_access,
    separate_reviewer,
    actor_id,
)
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


def create_app(db_path=None, auth_mode=None, identity_path=None):
    db_path = db_path or os.environ.get("AGENTSCOPE_DB", "data/agentscope.db")
    mode = auth_mode or os.environ.get("AGENTSCOPE_AUTH_MODE", "required")
    if mode not in {"required", "development"}:
        raise ValueError("Unknown authentication mode")
    identities = IdentityStore(
        identity_path
        or os.environ.get("AGENTSCOPE_IDENTITY_DB")
        or str(Path(db_path).parent / "identity.db")
    )
    tenants = TenantStores(db_path)

    @asynccontextmanager
    async def lifespan(app):
        yield
        tenants.close()
        identities.close()

    app = FastAPI(title="AgentScope", version="0.5.0", lifespan=lifespan)
    app.state.auth_mode = mode
    app.state.identities = identities
    app.state.tenants = tenants
    app.state.store = tenants.get("local")
    app.state.run_lock = asyncio.Lock()
    from fastapi.exceptions import RequestValidationError
    from fastapi.exception_handlers import request_validation_exception_handler
    from fastapi.responses import JSONResponse

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc):
        if request.url.path == "/api/auth/login":
            return JSONResponse({"detail": "Invalid login request"}, status_code=422)
        return await request_validation_exception_handler(request, exc)

    install_access(app, identities, tenants, mode)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"]
    )

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "version": "0.5.0",
            "storage": "sqlite",
            "scope": "local deployment; credential-bound tenants"
            if mode == "required"
            else "explicit unauthenticated development mode",
            "authentication": mode,
        }

    @app.get("/api/scenarios")
    def scenarios():
        return SCENARIOS

    @app.post("/v1/traces")
    async def ingest(request: Request, store: Store = Depends(tenant_store)):
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
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, "Invalid OTLP payload")
        try:
            store.ingest(spans)
        except Exception:
            raise HTTPException(503, "Trace storage unavailable", headers={"Retry-After": "1"})
        return Response(
            content=b"" if content_type == "application/x-protobuf" else b"{}",
            media_type=content_type,
        )

    @app.get("/api/traces")
    def traces(store: Store = Depends(tenant_store)):
        return [summarize(store.spans(t)) for t in store.trace_ids()]

    @app.get("/api/traces/{trace_id}")
    def trace(trace_id: str, store: Store = Depends(tenant_store)):
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
    def runs(store: Store = Depends(tenant_store)):
        return store.list("runs")

    @app.post("/api/runs")
    async def run(
        request: RunRequest, http: Request, store: Store = Depends(tenant_store)
    ):
        if app.state.run_lock.locked():
            raise HTTPException(409, "Another workload is running")
        async with app.state.run_lock:
            if request.transport == "mcp" and mode == "required":
                with identities.collector(http.state.actor) as export_token:
                    return await execute(request, store, export_token=export_token)
            return await execute(request, store)

    @app.get("/api/experiments")
    def experiments(store: Store = Depends(tenant_store)):
        return store.list("experiments", 20)

    @app.post("/api/experiments")
    async def evaluate(store: Store = Depends(tenant_store)):
        if app.state.run_lock.locked():
            raise HTTPException(409, "Another workload is running")
        async with app.state.run_lock:
            return await experiment(store)

    @app.get("/api/drift/reports")
    def drift_reports(store: Store = Depends(tenant_store)):
        return store.list("drift_reports", 30)

    @app.post("/api/drift/analyze")
    def drift_analyze(request: DriftRequest, store: Store = Depends(tenant_store)):
        return analyze(request, store)

    @app.post("/api/drift/demo")
    def drift_demo(request: DriftDemoRequest, store: Store = Depends(tenant_store)):
        return analyze(
            demo_request(request.scenario), store, source="synthetic seeded windows"
        )

    @app.get("/api/guardian/events")
    def guardian_events(store: Store = Depends(tenant_store)):
        return store.list("policy_events")

    @app.post("/api/guardian/demo")
    def guardian_demo(
        request: GuardianDemoRequest,
        http: Request,
        store: Store = Depends(tenant_store),
    ):
        event = demo_action(store, request.scenario)
        event["created_by"] = actor_id(http)
        store.put("policy_events", event)
        return event

    @app.post("/api/guardian/events/{event_id}/approve")
    def guardian_approve(
        event_id: str, http: Request, store: Store = Depends(tenant_store)
    ):
        try:
            event = store.get("policy_events", event_id)
            if not event:
                raise KeyError(event_id)
            separate_reviewer(http, event)
            result = approve(store, event_id)
            result.setdefault("approved_by", actor_id(http))
            store.put("policy_events", result)
            return result
        except KeyError:
            raise HTTPException(404, "Action not found")
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.get("/api/reviews")
    def reviews(store: Store = Depends(tenant_store)):
        return store.list("review_reports", 30)

    @app.post("/api/reviews")
    def review(request: TraceReviewRequest, store: Store = Depends(tenant_store)):
        try:
            return review_trace(store, request.trace_id)
        except KeyError:
            raise HTTPException(404, "Trace not found")

    @app.get("/api/replays")
    def replays(store: Store = Depends(tenant_store)):
        return store.list("replay_cases", 30)

    @app.post("/api/replays")
    async def replay(request: ReplayRequest, store: Store = Depends(tenant_store)):
        if app.state.run_lock.locked():
            raise HTTPException(409, "Another workload is running")
        async with app.state.run_lock:
            try:
                return await replay_trace(store, request.trace_id, request.variant)
            except ValueError as exc:
                raise HTTPException(409, str(exc))

    @app.get("/api/adapt")
    def adaptation(store: Store = Depends(tenant_store)):
        return adapt.overview(store)

    @app.post("/api/adapt/proposals")
    async def proposal(
        request: ProposalRequest, http: Request, store: Store = Depends(tenant_store)
    ):
        if app.state.run_lock.locked():
            raise HTTPException(409, "Another workload is running")
        async with app.state.run_lock:
            result = await adapt.propose(store, request.version)
            result["created_by"] = actor_id(http)
            store.put("adapt_proposals", result)
            return result

    @app.post("/api/adapt/proposals/{proposal_id}/approve")
    async def approve_proposal(
        proposal_id: str, http: Request, store: Store = Depends(tenant_store)
    ):
        if app.state.run_lock.locked():
            raise HTTPException(409, "Wait for the workload to complete")
        async with app.state.run_lock:
            try:
                proposal = store.get("adapt_proposals", proposal_id)
                if not proposal:
                    raise KeyError(proposal_id)
                separate_reviewer(http, proposal)
                result = adapt.start_canary(store, proposal_id)
                proposal = store.get("adapt_proposals", proposal_id)
                proposal["approved_by"] = actor_id(http)
                store.put("adapt_proposals", proposal)
                return result
            except KeyError:
                raise HTTPException(404, "Proposal not found")
            except ValueError as exc:
                raise HTTPException(409, str(exc))

    @app.post("/api/adapt/batch")
    async def batch(
        request: ValidationBatchRequest, store: Store = Depends(tenant_store)
    ):
        if app.state.run_lock.locked():
            raise HTTPException(409, "Another workload is running")
        async with app.state.run_lock:
            try:
                return await adapt.validation_batch(store, request.inject_outage)
            except ValueError as exc:
                raise HTTPException(409, str(exc))

    @app.post("/api/adapt/run")
    async def routed_run(
        request: RoutedRunRequest, store: Store = Depends(tenant_store)
    ):
        if app.state.run_lock.locked():
            raise HTTPException(409, "Another workload is running")
        async with app.state.run_lock:
            return await adapt.run_routed(store, request.scenario, request.request_id)

    @app.post("/api/adapt/{action}")
    async def transition(
        action: Literal["promote", "rollback"],
        http: Request,
        store: Store = Depends(tenant_store),
    ):
        if app.state.run_lock.locked():
            raise HTTPException(409, "Wait for the workload to complete")
        async with app.state.run_lock:
            try:
                if action == "promote":
                    current = adapt.state(store)
                    separate_reviewer(
                        http, store.get("adapt_proposals", current["rollout_id"] or "")
                    )
                return (
                    adapt.promote(store)
                    if action == "promote"
                    else adapt.rollback(store)
                )
            except ValueError as exc:
                raise HTTPException(409, str(exc))

    @app.get("/api/access/audit")
    def access_audit(store: Store = Depends(tenant_store)):
        return store.list("access_audit", 100)

    dist = Path(__file__).resolve().parent.parent / "web" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="dashboard")
    return app


app = create_app()
