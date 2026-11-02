"""Bounded trace-derived monitoring. Distribution shifts are not quality verdicts."""

import json
import math
import time
import uuid
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .drift import MetricWindow, DriftRequest, analyze


class TraceWindows(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    service: str = Field(min_length=1, max_length=256)
    reference_start: float = Field(ge=0)
    reference_end: float = Field(ge=0)
    current_start: float = Field(ge=0)
    current_end: float = Field(ge=0)

    @model_validator(mode="after")
    def windows(self):
        if (
            not self.reference_start
            < self.reference_end
            <= self.current_start
            < self.current_end
        ):
            raise ValueError("Use ordered, nonoverlapping windows")
        if self.current_end > time.time() - 5:
            raise ValueError("Windows must end at least five seconds ago")
        if self.current_end - self.reference_start > 31 * 86400:
            raise ValueError("Comparison must fit within 31 days")
        return self


METRICS = [
    ("duration_ms", "Execution duration", "ms"),
    ("tokens", "Reported tokens", "tokens"),
    ("tool_error_rate", "Tool error rate", "%"),
    ("retries", "Explicit retry calls", "calls"),
]


def numeric(value):
    return type(value) in (float, int) and math.isfinite(value) and value >= 0


def observations(store, service, start, end):
    roots = store.db.execute(
        """SELECT payload FROM spans WHERE start_ns>=? AND start_ns<?
        AND json_extract(payload,'$.parent_id') IS NULL
        AND json_extract(payload,'$.resource."service.name"')=? ORDER BY start_ns,trace_id LIMIT 257""",
        (int(start * 1e9), int(end * 1e9), service),
    ).fetchall()
    if len(roots) > 256:
        raise ValueError(
            "Window exceeds 256 root spans; narrow the time range or service"
        )
    groups = {}
    for row in roots:
        root = json.loads(row[0])
        groups[root["trace_id"]] = store.spans(root["trace_id"])
    evidence = {key: [] for key, _, _ in METRICS}
    excluded = []
    for trace_id, spans in groups.items():
        ids = {s["span_id"] for s in spans}
        if (
            sum(not s["parent_id"] for s in spans) != 1
            or any(s["parent_id"] and s["parent_id"] not in ids for s in spans)
            or any(
                s["end_ns"] > int(end * 1e9) or s["end_ns"] < s["start_ns"]
                for s in spans
            )
        ):
            excluded.append(trace_id)
            continue

        def add(key, value):
            evidence[key].append({"trace_id": trace_id, "value": value})

        add(
            "duration_ms",
            (max(s["end_ns"] for s in spans) - min(s["start_ns"] for s in spans)) / 1e6,
        )
        usage = [
            s["attributes"]
            for s in spans
            if any(
                k in s["attributes"]
                for k in (
                    "gen_ai.usage.input_tokens",
                    "gen_ai.usage.output_tokens",
                    "gen_ai.request.model",
                )
            )
        ]
        if usage and all(
            numeric(a.get("gen_ai.usage.input_tokens"))
            and numeric(a.get("gen_ai.usage.output_tokens"))
            for a in usage
        ):
            total = sum(
                a["gen_ai.usage.input_tokens"] + a["gen_ai.usage.output_tokens"]
                for a in usage
            )
            if numeric(total):
                add("tokens", total)
        # SERVER tool spans duplicate CLIENT invocations across MCP boundaries.
        tools = [
            s for s in spans if s["attributes"].get("tool.name") and s["kind"] != 2
        ]
        if tools:
            add(
                "tool_error_rate",
                100 * sum(s["status"] == "ERROR" for s in tools) / len(tools),
            )
            if all(
                type(s["attributes"].get("tool.attempt")) is int
                and s["attributes"]["tool.attempt"] >= 1
                for s in tools
            ):
                add("retries", sum(s["attributes"]["tool.attempt"] > 1 for s in tools))
    return {
        "root_candidates": len(roots),
        "eligible_traces": len(groups) - len(excluded),
        "excluded_trace_ids": excluded,
        "evidence": evidence,
    }


def compare(request, store):
    # One database read transaction freezes both windows against other connections.
    with store.lock:
        store.db.execute("BEGIN")
        try:
            reference = observations(
                store, request.service, request.reference_start, request.reference_end
            )
            current = observations(
                store, request.service, request.current_start, request.current_end
            )
        finally:
            store.db.rollback()
    metrics = []
    for key, name, unit in METRICS:
        x, y = reference["evidence"][key], current["evidence"][key]
        if min(len(x), len(y)) >= 30:
            metrics.append(
                MetricWindow(
                    name=name,
                    kind="operational",
                    unit=unit,
                    reference=[r["value"] for r in x],
                    current=[r["value"] for r in y],
                )
            )

    # Reuse statistical implementation without persisting an incomplete report.
    class Sink:
        def put(self, *args):
            pass

    if metrics:
        report = analyze(
            DriftRequest(label="Collected trace comparison", metrics=metrics),
            Sink(),
            source="collected_traces",
        )
    else:
        report = {
            "id": str(uuid.uuid4()),
            "created_at": time.time(),
            "label": "Collected trace comparison",
            "source": "collected_traces",
            "rows": [],
            "alert_count": 0,
            "alpha": 0.05,
            "min_effect": 0.2,
            "method": "No tests run: insufficient observations",
        }
    tested = {r["name"]: r for r in report["rows"]}
    rows = []
    for key, name, unit in METRICS:
        x, y = reference["evidence"][key], current["evidence"][key]
        row = tested.get(
            name,
            {
                "name": name,
                "unit": unit,
                "n_reference": len(x),
                "n_current": len(y),
                "shift_detected": False,
            },
        )
        row.update(
            {
                "key": key,
                "status": "tested" if name in tested else "insufficient",
                "missing_reference": reference["eligible_traces"] - len(x),
                "missing_current": current["eligible_traces"] - len(y),
                "reference_evidence": x,
                "current_evidence": y,
            }
        )
        rows.append(row)
    report.update(
        {
            "rows": rows,
            "windows": request.model_dump(),
            "coverage": {
                "reference": {k: v for k, v in reference.items() if k != "evidence"},
                "current": {k: v for k, v in current.items() if k != "evidence"},
            },
            "limitations": "Exploratory monitoring assumes exchangeable observations. Time dependence, repeated comparisons, workload mix and sampling can confound results. Missing telemetry is not zero. A shift does not establish quality degradation or causality. Roots and parent coverage cannot prove all spans arrived; saved evidence is a snapshot, linked traces may later change.",
        }
    )
    store.put("drift_reports", report)
    return report
