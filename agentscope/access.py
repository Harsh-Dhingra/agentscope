"""Credential-bound tenant routing, role checks, and browser session protection."""

import hashlib
import hmac
import re
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from .identity import IdentityStore, PERMISSIONS, SESSION_SECONDS
from .store import Store

COOKIE = "agentscope_session"
OPERATIONS = {
    "/api/runs",
    "/api/experiments",
    "/api/drift/analyze",
    "/api/drift/demo",
    "/api/drift/traces",
    "/api/guardian/demo",
    "/api/reviews",
    "/api/replays",
    "/api/adapt/proposals",
    "/api/adapt/batch",
    "/api/adapt/run",
}
APPROVAL = re.compile(r"^/api/(guardian/events|adapt/proposals)/[^/]+/approve$")


class TenantStores:
    def __init__(self, legacy_path):
        self.legacy_path = legacy_path
        self.lock = threading.RLock()
        self.stores = {}
        self.root = Path(legacy_path).parent / "tenants"

    def get(self, tenant):
        with self.lock:
            if tenant not in self.stores:
                # Tenant is read exclusively from the server's credential registry.
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", tenant):
                    raise ValueError("Invalid tenant")
                path = (
                    self.legacy_path
                    if tenant == "local"
                    else (
                        ":memory:"
                        if self.legacy_path == ":memory:"
                        else str(
                            self.root
                            / (hashlib.sha256(tenant.encode()).hexdigest() + ".db")
                        )
                    )
                )
                self.stores[tenant] = Store(path)
            return self.stores[tenant]

    def close(self):
        for store in self.stores.values():
            store.close()


def tenant_store(request: Request):
    return request.state.store


def permitted(role, method, path):
    if role == "developer":
        return True
    if path in {"/v1/traces", "/v1/logs"}:
        return method == "POST" and role in {"collector", "operator"}
    if role == "collector":
        return False
    if method in {"GET", "HEAD"}:
        return "read" in PERMISSIONS[role]
    if method != "POST":
        return False
    if path == "/api/auth/logout":
        return True
    if path in OPERATIONS:
        return role == "operator"
    if APPROVAL.fullmatch(path) or path in {
        "/api/adapt/promote",
        "/api/adapt/rollback",
    }:
        return role == "reviewer"
    return False


def separate_reviewer(request, item):
    if request.app.state.auth_mode == "required" and (
        not item
        or not item.get("created_by")
        or item["created_by"] == request.state.actor["subject"]
    ):
        raise HTTPException(
            403,
            "A different authenticated principal must review this action; legacy proposals must be recreated",
        )


def actor_id(request):
    return request.state.actor["subject"]


def install_access(app, identities: IdentityStore, tenants: TenantStores, mode):
    attempts = deque()
    attempt_lock = threading.Lock()

    def audit(request, status):
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return
        actor = getattr(request.state, "actor", None)
        if not actor:
            return
        # No request bodies, credentials, query strings, or raw path parameters.
        template = getattr(request.scope.get("route"), "path", "unmatched")
        tenants.get(actor["tenant"]).put(
            "access_audit",
            {
                "id": str(uuid.uuid4()),
                "created_at": time.time(),
                "subject": actor["subject"],
                "role": actor["role"],
                "tenant": actor["tenant"],
                "method": request.method,
                "route": template,
                "status": status,
            },
        )

    @app.middleware("http")
    async def access(request, call_next):
        path = request.url.path
        protected = path.startswith("/api/") or path.startswith("/v1/")
        public = path in {"/api/health", "/api/auth/session", "/api/auth/login"}
        if protected:
            request.state.actor = None
            header = request.headers.get("authorization")
            if mode == "development":
                request.state.actor = {
                    "subject": "local-developer",
                    "tenant": "local",
                    "role": "developer",
                    "permissions": PERMISSIONS["developer"],
                }
            elif header:
                scheme, _, key = header.partition(" ")
                request.state.actor = (
                    identities.authenticate(key) if scheme.lower() == "bearer" else None
                )
            else:
                request.state.actor = identities.session(request.cookies.get(COOKIE))
            if request.state.actor:
                request.state.store = tenants.get(request.state.actor["tenant"])
            mutating = request.method not in {"GET", "HEAD", "OPTIONS"}
            origin = request.headers.get("origin")
            if mutating and origin and origin != str(request.base_url).rstrip("/"):
                audit(request, 403)
                return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
            if not public:
                if not request.state.actor:
                    return JSONResponse(
                        {"detail": "Authentication required"},
                        status_code=401,
                        headers={
                            "WWW-Authenticate": "Bearer",
                            "Cache-Control": "no-store",
                        },
                    )
                if mode == "required" and not header and mutating:
                    expected = request.state.actor.get("csrf_token", "")
                    if not expected or not hmac.compare_digest(
                        request.headers.get("x-csrf-token", "").encode(),
                        expected.encode(),
                    ):
                        audit(request, 403)
                        return JSONResponse(
                            {"detail": "CSRF token required"}, status_code=403
                        )
                if not permitted(request.state.actor["role"], request.method, path):
                    audit(request, 403)
                    return JSONResponse(
                        {"detail": "Your role does not permit this operation"},
                        status_code=403,
                    )
        response = await call_next(request)
        if protected:
            response.headers["Cache-Control"] = "no-store"
            audit(request, response.status_code)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    class Login(BaseModel):
        model_config = ConfigDict(extra="forbid")
        api_key: str = Field(min_length=20, max_length=128)

    @app.get("/api/auth/session")
    def session(request: Request):
        actor = request.state.actor
        return {
            "mode": mode,
            "configured": identities.configured(),
            "authenticated": bool(actor),
            **({k: v for k, v in actor.items() if k != "key_id"} if actor else {}),
        }

    @app.post("/api/auth/login")
    def login(body: Login, request: Request):
        if mode != "required":
            raise HTTPException(
                409, "Authentication is disabled in explicit development mode"
            )
        with attempt_lock:
            now = time.monotonic()
            while attempts and attempts[0] < now - 60:
                attempts.popleft()
            if len(attempts) >= 20:
                raise HTTPException(
                    429,
                    "Too many login attempts; try again in a minute",
                    headers={"Retry-After": "60"},
                )
            attempts.append(now)
        try:
            secret, actor = identities.create_session(body.api_key)
        except ValueError:
            raise HTTPException(401, "Invalid or expired dashboard credential")
        old = request.cookies.get(COOKIE)
        if old:
            identities.logout(old)
        request.state.actor = actor
        request.state.store = tenants.get(actor["tenant"])
        response = JSONResponse(
            {
                "authenticated": True,
                "mode": mode,
                **{k: v for k, v in actor.items() if k != "key_id"},
            }
        )
        response.set_cookie(
            COOKIE,
            secret,
            max_age=SESSION_SECONDS,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            path="/",
        )
        return response

    @app.post("/api/auth/logout")
    def logout(request: Request):
        identities.logout(request.cookies.get(COOKIE, ""))
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(COOKIE, path="/")
        return response
