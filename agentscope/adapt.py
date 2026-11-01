"""Evaluated configuration changes and a local, synthetic-traffic canary router."""

import hashlib
import json
import time
import uuid
from pathlib import Path
from .demo import RunRequest, SCENARIOS, execute
from .telemetry import create_tracer
from opentelemetry.trace import Status, StatusCode

VERSIONS = {
    "baseline-v1": {
        "id": "baseline-v1",
        "variant": "baseline",
        "source_filter": "first result",
        "retry_budget": 4,
        "fallback": "unverified answer",
    },
    "guarded-v2": {
        "id": "guarded-v2",
        "variant": "guarded",
        "source_filter": "current policy",
        "retry_budget": 2,
        "fallback": "explicit escalation",
    },
}
MIN_CANARY_RUNS = 5


def digest(version):
    data = (
        Path(__file__).with_name("demo.py").read_bytes()
        + json.dumps(VERSIONS[version], sort_keys=True).encode()
    )
    return hashlib.sha256(data).hexdigest()


def state(store):
    with store.lock:
        value = store.get("deployment_state", "local")
        if value is None:
            value = {
                "id": "local",
                "revision": 0,
                "stable": "baseline-v1",
                "candidate": None,
                "candidate_percent": 0,
                "previous": None,
                "rollout_id": None,
            }
            store.put("deployment_state", value)
        return value


def audit(store, kind, detail):
    event = {"id": str(uuid.uuid4()), "created_at": time.time(), "kind": kind, **detail}
    store.put("adapt_events", event)


async def propose(store, version):
    current = state(store)
    rows = [
        await execute(
            RunRequest(scenario=s, variant=VERSIONS[version]["variant"]), store
        )
        for s in SCENARIOS
    ]
    gates = [
        {
            "name": "All four fixture scenarios pass",
            "passed": all(r["passed"] for r in rows),
        },
        {
            "name": "No telemetry export failures",
            "passed": all(r["export_failures"] == 0 for r in rows),
        },
    ]
    proposal = {
        "id": str(uuid.uuid4()),
        "created_at": time.time(),
        "candidate": version,
        "based_on_revision": current["revision"],
        "code_digest": digest(version),
        "rows": rows,
        "gates": gates,
        "eligible": all(g["passed"] for g in gates),
        "status": "evaluated",
        "dataset": "incident-fixtures-v1",
        "runtime": "scripted",
        "limitations": "A four-case authored regression gate; not a production readiness or general model-quality assessment.",
    }
    store.put("adapt_proposals", proposal)
    audit(
        store,
        "evaluation_completed",
        {
            "proposal_id": proposal["id"],
            "candidate": version,
            "eligible": proposal["eligible"],
        },
    )
    return proposal


def start_canary(store, proposal_id):
    with store.lock:
        proposal = store.get("adapt_proposals", proposal_id)
        if not proposal:
            raise KeyError(proposal_id)
        current = state(store)
        if not proposal["eligible"] or proposal["status"] != "evaluated":
            raise ValueError("Only an eligible, unused evaluation can enter canary")
        if proposal["code_digest"] != digest(proposal["candidate"]):
            raise ValueError("Code changed; evaluate this candidate again")
        if current["revision"] != proposal["based_on_revision"] or current["candidate"]:
            raise ValueError(
                "Deployment changed; evaluate against the current revision"
            )
        if current["stable"] == proposal["candidate"]:
            raise ValueError("Candidate is already the stable version")
        current.update(
            candidate=proposal["candidate"],
            candidate_percent=20,
            rollout_id=proposal_id,
            revision=current["revision"] + 1,
        )
        proposal["status"] = "canary"
        store.put("deployment_state", current)
        store.put("adapt_proposals", proposal)
        audit(
            store,
            "canary_started",
            {
                "proposal_id": proposal_id,
                "candidate": current["candidate"],
                "candidate_percent": 20,
                "approval": "explicit local demo action",
            },
        )
        return current


def route(current, request_id):
    bucket = int(hashlib.sha256(request_id.encode()).hexdigest()[:8], 16) % 100
    return (
        current["candidate"]
        if current["candidate"] and bucket < current["candidate_percent"]
        else current["stable"]
    )


def outcomes(store, current):
    return [
        r
        for r in store.list("canary_runs", 10000)
        if r["rollout_id"] == current["rollout_id"] and r["route"] == "candidate"
    ]


def promote(store):
    with store.lock:
        current = state(store)
        samples = outcomes(store, current)
        if not current["candidate"] or len(samples) < MIN_CANARY_RUNS:
            raise ValueError("At least five candidate validation runs are required")
        if not all(r["passed"] for r in samples):
            raise ValueError("Failed canary outcomes prevent promotion")
        proposal = store.get("adapt_proposals", current["rollout_id"])
        if not proposal or proposal["code_digest"] != digest(current["candidate"]):
            raise ValueError("Code changed; evaluate again")
        previous = current["stable"]
        current.update(
            stable=current["candidate"],
            candidate=None,
            candidate_percent=0,
            previous=previous,
            revision=current["revision"] + 1,
        )
        store.put("deployment_state", current)
        audit(
            store,
            "promoted",
            {
                "stable": current["stable"],
                "previous": previous,
                "candidate_runs": len(samples),
            },
        )
        return current


def rollback(store, reason="Explicit local rollback"):
    with store.lock:
        current = state(store)
        if not current["candidate"] and not current["previous"]:
            raise ValueError("No candidate or previous version to roll back")
        old = current["candidate"] or current["stable"]
        if not current["candidate"]:
            current["stable"] = current["previous"]
            current["previous"] = None
        current.update(
            candidate=None, candidate_percent=0, revision=current["revision"] + 1
        )
        store.put("deployment_state", current)
        audit(
            store,
            "rolled_back",
            {"from": old, "stable": current["stable"], "reason": reason},
        )
        return current


async def run_routed(store, scenario, request_id, inject_outage=False):
    current = state(store)
    version = route(current, request_id)
    candidate = bool(current["candidate"] and version == current["candidate"])
    if inject_outage and not candidate:
        raise ValueError("Fault injection is restricted to candidate probes")
    if inject_outage:
        tracer, provider, _ = create_tracer(store=store, service="canary-probe")
        with tracer.start_as_current_span(
            "candidate.unavailable",
            attributes={
                "agent.runtime": "scripted",
                "agent.config_version": version,
                "agent.scenario": scenario,
                "eval.passed": False,
                "eval.name": "Injected candidate availability failure",
                "error.type": "InjectedCandidateOutage",
            },
        ) as span:
            span.set_status(Status(StatusCode.ERROR))
            trace_id = f"{span.get_span_context().trace_id:032x}"
        provider.shutdown()
        result = {
            "id": str(uuid.uuid4()),
            "trace_id": trace_id,
            "passed": False,
            "outcome": "failed",
            "scenario": scenario,
        }
    else:
        result = await execute(
            RunRequest(scenario=scenario, variant=VERSIONS[version]["variant"]), store
        )
    record = {
        "id": str(uuid.uuid4()),
        "created_at": time.time(),
        "rollout_id": current["rollout_id"],
        "version": version,
        "route": "candidate" if candidate else "stable",
        "request_id": request_id,
        "trace_id": result["trace_id"],
        "scenario": scenario,
        "passed": result["passed"],
        "outcome": result["outcome"],
        "injected_outage": inject_outage,
    }
    with store.lock:
        store.put("canary_runs", record)
        latest = state(store)
        if (
            candidate
            and not record["passed"]
            and latest["revision"] == current["revision"]
        ):
            rollback(
                store,
                "Candidate assertion/availability failure during synthetic validation",
            )
    return record


async def validation_batch(store, inject_outage=False):
    current = state(store)
    if not current["candidate"]:
        raise ValueError("Start a canary first")
    # Deliberately balanced probes, not a representative traffic-rate sample.
    ids = {"candidate": [], "stable": []}
    prefix = str(uuid.uuid4())
    i = 0
    while min(map(len, ids.values())) < 5:
        key = f"{prefix}:{i}"
        i += 1
        target = (
            "candidate" if route(current, key) == current["candidate"] else "stable"
        )
        if len(ids[target]) < 5:
            ids[target].append(key)
    rows = []
    for target in ("candidate", "stable"):
        for i, key in enumerate(ids[target]):
            rows.append(
                await run_routed(
                    store,
                    list(SCENARIOS)[i % 4],
                    key,
                    inject_outage=inject_outage and target == "candidate" and i == 0,
                )
            )
            if inject_outage:
                return rows
    return rows


def overview(store):
    current = state(store)
    return {
        "state": current,
        "versions": list(VERSIONS.values()),
        "proposals": store.list("adapt_proposals", 20),
        "events": store.list("adapt_events", 30),
        "runs": store.list("canary_runs", 50),
        "candidate_samples": len(outcomes(store, current))
        if current["candidate"]
        else 0,
        "minimum_samples": MIN_CANARY_RUNS,
    }
