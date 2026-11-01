"""Instrumented LangGraph incident-analysis workload, separate from Salesforce case prep."""

import asyncio
import json
import os

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
import sys
import time
import uuid
from typing import Literal, TypedDict
import httpx
from langgraph.graph import StateGraph, START, END
from opentelemetry import propagate
from opentelemetry.trace import Status, StatusCode, SpanKind
from pydantic import BaseModel, ConfigDict
from .telemetry import create_tracer

SCENARIOS = {
    "healthy": {
        "label": "Grounded response",
        "description": "Research and answer from the current incident runbook.",
    },
    "stale_evidence": {
        "label": "Stale evidence",
        "description": "An expired runbook ranks first; compare version filtering.",
    },
    "tool_timeout": {
        "label": "Tool timeout",
        "description": "Inject a dependency timeout; compare truthful fallback.",
    },
    "retry_loop": {
        "label": "Retry storm",
        "description": "Inject repeated failures; compare bounded recovery.",
    },
}


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Literal["healthy", "stale_evidence", "tool_timeout", "retry_loop"] = (
        "stale_evidence"
    )
    variant: Literal["baseline", "guarded"] = "guarded"
    runtime: Literal["scripted", "ollama"] = "scripted"
    transport: Literal["inprocess", "mcp"] = "inprocess"


class AgentState(TypedDict, total=False):
    document: dict | None
    attempts: int
    answer: str
    outcome: str
    model_failed: bool
    assertions: list[dict]


def runbook(current=True):
    return {
        "id": "incident-runbook",
        "version": "v3" if current else "v1",
        "current": current,
        "retention_days": 30 if current else 90,
        "text": f"Diagnostic logs must be retained for {30 if current else 90} days. Source: incident-runbook {'v3' if current else 'v1'}.",
    }


async def mcp_lookup(current, tracer):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    carrier = {}
    propagate.inject(carrier)
    env = {
        k: v for k, v in os.environ.items() if k in {"PATH", "PYTHONPATH", "SYSTEMROOT"}
    }
    env["AGENTSCOPE_EXPORT_ENDPOINT"] = os.environ.get(
        "AGENTSCOPE_DEMO_EXPORT_ENDPOINT", "http://127.0.0.1:8765/v1/traces"
    )
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "agentscope.mcp_server"], env=env
    )
    async with asyncio.timeout(15):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "lookup_runbook",
                    {"current": current, "traceparent": carrier.get("traceparent", "")},
                )
                if result.isError:
                    raise RuntimeError("MCP_TOOL_ERROR")
                return json.loads(result.content[0].text)


async def execute(request: RunRequest, store):
    started = time.perf_counter()
    run_id = str(uuid.uuid4())
    tracer, provider, exporter = create_tracer(store=store, service="incident-agent")
    spec = request.model_dump()
    model = os.environ.get("AGENTSCOPE_OLLAMA_MODEL", "qwen3:8b")

    async def plan(state):
        with tracer.start_as_current_span(
            "coordinator.plan",
            attributes={"agent.role": "coordinator", "agent.step": "plan"},
        ):
            await asyncio.sleep(0.01)
            return {"attempts": 0}

    async def research(state):
        with tracer.start_as_current_span(
            "researcher.delegate", attributes={"agent.role": "researcher"}
        ):
            failing = request.scenario in {"tool_timeout", "retry_loop"}
            budget = (
                4
                if request.scenario == "retry_loop" and request.variant == "baseline"
                else 2
                if failing and request.variant == "guarded"
                else 1
            )
            document = None
            for attempt in range(1, budget + 1):
                with tracer.start_as_current_span(
                    "tool.lookup_runbook",
                    kind=SpanKind.CLIENT,
                    attributes={
                        "tool.name": "lookup_runbook",
                        "tool.attempt": attempt,
                        "agent.protocol": request.transport,
                    },
                    record_exception=False,
                ) as span:
                    try:
                        await asyncio.sleep(0.03)
                        if failing:
                            raise TimeoutError("Injected test fault")
                        current = not (
                            request.scenario == "stale_evidence"
                            and request.variant == "baseline"
                        )
                        document = (
                            await mcp_lookup(current, tracer)
                            if request.transport == "mcp"
                            else runbook(current)
                        )
                        span.set_attribute("tool.result", "success")
                        with tracer.start_as_current_span(
                            "retrieval.evidence",
                            attributes={
                                "retrieval.document_id": document["id"],
                                "retrieval.policy_version": document["version"],
                                "retrieval.current": document["current"],
                            },
                        ):
                            pass
                        break
                    except Exception as exc:
                        span.set_status(Status(StatusCode.ERROR))
                        span.set_attribute("error.type", type(exc).__name__)
                        span.set_attribute("tool.result", "unavailable")
                if attempt < budget:
                    await asyncio.sleep(0.02 * attempt)
            return {"document": document, "attempts": attempt}

    async def answer(state):
        with tracer.start_as_current_span(
            "analyst.answer", attributes={"agent.role": "analyst"}
        ):
            doc = state["document"]
            if doc is None and request.variant == "guarded":
                return {
                    "answer": "I cannot verify the current retention policy because the runbook service is unavailable. Escalate to the incident owner.",
                    "outcome": "escalated",
                    "model_failed": False,
                }
            attrs = {
                "gen_ai.provider.name": "ollama"
                if request.runtime == "ollama"
                else "scripted-fixture",
                "gen_ai.request.model": model
                if request.runtime == "ollama"
                else "none",
                "gen_ai.operation.name": "chat",
            }
            with tracer.start_as_current_span(
                "model.generate", attributes=attrs, record_exception=False
            ) as span:
                if request.runtime == "scripted":
                    await asyncio.sleep(0.04)
                    days = doc["retention_days"] if doc else 90
                    return {
                        "answer": f"Retain diagnostic logs for {days} days. Source: incident-runbook {doc['version'] if doc else 'unverified'}.",
                        "outcome": "answered",
                        "model_failed": False,
                    }
                base = os.environ.get("AGENTSCOPE_OLLAMA_URL", "http://127.0.0.1:11434")
                # The endpoint is deployment configuration, never client-supplied.
                from urllib.parse import urlparse

                if (
                    urlparse(base).hostname
                    not in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
                    or ":cloud" in model
                ):
                    raise ValueError(
                        "This release only supports a local Ollama endpoint/model"
                    )
                context = (
                    doc["text"]
                    if doc
                    else "Runbook service unavailable; there is no verified evidence."
                )
                try:
                    async with httpx.AsyncClient(
                        timeout=120, trust_env=False
                    ) as client:
                        r = await client.post(
                            base + "/api/chat",
                            json={
                                "model": model,
                                "stream": False,
                                "think": False,
                                "options": {"temperature": 0, "num_predict": 128},
                                "messages": [
                                    {
                                        "role": "system",
                                        "content": "Answer in one short sentence using only the supplied evidence. Cite the source and version. If evidence is unavailable say you cannot verify and escalate. Do not invent a policy.",
                                    },
                                    {
                                        "role": "user",
                                        "content": "How long should diagnostic logs be retained?\nEvidence: "
                                        + context,
                                    },
                                ],
                            },
                        )
                        r.raise_for_status()
                        data = r.json()
                    for key, out in [
                        ("prompt_eval_count", "gen_ai.usage.input_tokens"),
                        ("eval_count", "gen_ai.usage.output_tokens"),
                    ]:
                        if isinstance(data.get(key), int):
                            span.set_attribute(out, data[key])
                    return {
                        "answer": data["message"]["content"],
                        "outcome": "answered",
                        "model_failed": False,
                    }
                except Exception as exc:
                    span.set_status(Status(StatusCode.ERROR))
                    span.set_attribute("error.type", type(exc).__name__)
                    return {
                        "answer": "Local model unavailable. No model response was substituted.",
                        "outcome": "failed",
                        "model_failed": True,
                    }

    def evaluate(state):
        import re

        text = state["answer"].lower()
        has_current = (
            bool(re.search(r"\b30\s*(?:calendar\s+)?days?\b", text))
            and "90" not in text
        )
        expected_escalation = request.scenario in {"tool_timeout", "retry_loop"}
        assertions = [
            {
                "name": "Expected completion or escalation",
                "passed": state["outcome"]
                == ("escalated" if expected_escalation else "answered"),
            },
            {
                "name": "Current evidence or truthful fallback",
                "passed": (
                    (state["outcome"] == "escalated" and state["document"] is None)
                    if expected_escalation
                    else bool(
                        state["document"]
                        and state["document"]["current"]
                        and has_current
                    )
                ),
            },
            {
                "name": "Bounded tool attempts (at most two)",
                "passed": state["attempts"] <= 2,
            },
            {
                "name": "Runtime completed without model failure",
                "passed": not state["model_failed"],
            },
        ]
        for a in assertions:
            with tracer.start_as_current_span(
                "evaluation.assertion",
                attributes={"eval.name": a["name"], "eval.passed": a["passed"]},
            ):
                pass
        return {"assertions": assertions}

    builder = StateGraph(AgentState)
    for name, fn in [
        ("plan", plan),
        ("research", research),
        ("answer", answer),
        ("evaluate", evaluate),
    ]:
        builder.add_node(name, fn)
    for source, target in [
        (START, "plan"),
        ("plan", "research"),
        ("research", "answer"),
        ("answer", "evaluate"),
        ("evaluate", END),
    ]:
        builder.add_edge(source, target)
    graph = builder.compile()
    with tracer.start_as_current_span(
        "incident-analysis",
        attributes={
            "agent.run_id": run_id,
            "agent.scenario": request.scenario,
            "agent.variant": request.variant,
            "agent.runtime": request.runtime,
        },
    ) as root:
        trace_id = f"{root.get_span_context().trace_id:032x}"
        state = await graph.ainvoke({})
        root.set_attribute("agent.outcome", state["outcome"])
        root.set_attribute("eval.passed", all(a["passed"] for a in state["assertions"]))
        root.set_attribute("eval.name", "All workload assertions")
    provider.force_flush()
    provider.shutdown()
    result = {
        "id": run_id,
        "trace_id": trace_id,
        **spec,
        "answer": state["answer"],
        "outcome": state["outcome"],
        "assertions": state["assertions"],
        "passed": all(a["passed"] for a in state["assertions"]),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "export_failures": exporter.failed_batches,
        "created_at": time.time(),
    }
    store.put("runs", result)
    return result


async def experiment(store):
    rows = []
    for variant in ["baseline", "guarded"]:
        for scenario in SCENARIOS:
            rows.append(
                await execute(RunRequest(scenario=scenario, variant=variant), store)
            )
    result = {
        "id": str(uuid.uuid4()),
        "dataset": "incident-fixtures-v1",
        "runtime": "scripted",
        "created_at": time.time(),
        "rows": rows,
        "summary": {
            v: {
                "passed": sum(r["passed"] for r in rows if r["variant"] == v),
                "total": sum(r["variant"] == v for r in rows),
            }
            for v in ["baseline", "guarded"]
        },
        "limitations": "Four authored fault scenarios; deterministic scripted responses. This measures regression behavior, not general LLM quality or production impact.",
    }
    store.put("experiments", result)
    return result
