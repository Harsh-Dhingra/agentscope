"""Deterministic policy enforcement around synthetic tools.

Principals are server-defined demo identities. This is not production authentication.
"""

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class Principal:
    id: str
    role: str


class ToolAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: Literal["read_health", "restart_worker", "export_logs", "delete_namespace"]
    target: str = Field(default="worker-alpha", max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=100)


def decide(principal: Principal, action: ToolAction, approved=False):
    if action.target != "worker-alpha":
        return "denied", "Target is outside the allowed demo resource scope."
    if action.tool == "read_health":
        return "allowed", "Read-only health inspection is permitted."
    if action.tool in {"export_logs", "delete_namespace"}:
        return "denied", "This tool is not permitted by the deployment policy."
    if principal.role != "operator":
        return "denied", "This principal does not have the operator role."
    if not approved:
        return (
            "approval_required",
            "Restarting a worker requires explicit human review.",
        )
    return "allowed", "Operator role, resource scope and human approval verified."


def submit(store, principal: Principal, action: ToolAction):
    decision, reason = decide(principal, action)
    event = {
        "id": str(uuid.uuid4()),
        "created_at": time.time(),
        "principal": principal.id,
        "role": principal.role,
        "action": action.model_dump(),
        "decision": decision,
        "reason": reason,
        "executed": False,
        "result": None,
        "source": "synthetic demo identity and tool",
    }
    if decision == "allowed":
        event.update(execute_once(store, principal, action))
    store.put("policy_events", event)
    return event


def execute_once(store, principal, action, approved=False):
    decision, reason = decide(principal, action, approved=approved)
    if decision != "allowed":
        raise ValueError(reason)
    fingerprint = hashlib.sha256(
        json.dumps(
            {"principal": principal.id, "tool": action.tool, "target": action.target},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    with store.lock, store.db:
        existing = store.db.execute(
            "SELECT fingerprint,payload FROM gateway_actions WHERE action_key=?",
            (action.idempotency_key,),
        ).fetchone()
        if existing:
            if existing["fingerprint"] != fingerprint:
                raise ValueError(
                    "Idempotency key was already used for a different action"
                )
            return {
                "executed": True,
                "replayed": True,
                "result": json.loads(existing["payload"]),
            }
        if action.tool == "read_health":
            result = {"resource": action.target, "status": "healthy", "synthetic": True}
        elif action.tool == "restart_worker":
            count = (
                store.db.execute(
                    "SELECT count FROM gateway_resources WHERE id=?", (action.target,)
                ).fetchone()[0]
                + 1
            )
            store.db.execute(
                "UPDATE gateway_resources SET count=? WHERE id=?",
                (count, action.target),
            )
            result = {
                "resource": action.target,
                "restart_count": count,
                "synthetic": True,
            }
        else:
            raise ValueError("Tool is not executable")
        store.db.execute(
            "INSERT INTO gateway_actions VALUES(?,?,?)",
            (action.idempotency_key, fingerprint, json.dumps(result)),
        )
        return {"executed": True, "replayed": False, "result": result}


def approve(store, event_id):
    with store.lock:
        event = store.get("policy_events", event_id)
        if not event:
            raise KeyError(event_id)
        if event["decision"] == "allowed" and event.get("approved_at"):
            return {**event, "replayed": True}
        if event["decision"] != "approval_required":
            raise ValueError("Only pending actions can be approved")
        principal = Principal(event["principal"], event["role"])
        action = ToolAction(**event["action"])
        decision, reason = decide(principal, action, approved=True)
        if decision != "allowed":
            raise ValueError(reason)
        event.update(execute_once(store, principal, action, approved=True))
        event.update(
            {"decision": "allowed", "reason": reason, "approved_at": time.time()}
        )
        store.put("policy_events", event)
        return event


def demo_action(store, scenario):
    mapping = {
        "allowed_read": (Principal("demo-auditor", "auditor"), "read_health"),
        "unauthorized_write": (Principal("demo-auditor", "auditor"), "restart_worker"),
        "approval_required": (Principal("demo-operator", "operator"), "restart_worker"),
        "blocked_export": (Principal("demo-operator", "operator"), "export_logs"),
    }
    principal, tool = mapping[scenario]
    return submit(
        store, principal, ToolAction(tool=tool, idempotency_key=str(uuid.uuid4()))
    )
