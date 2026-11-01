"""Bounded evidence analyzers with deterministic aggregation, not LLM consensus."""

import time
import uuid
from .analysis import summarize


def vote(role, verdict, summary, evidence):
    return {
        "role": role,
        "verdict": verdict,
        "summary": summary,
        "evidence": evidence,
        "method": "deterministic analyzer v1",
    }


def reliability(spans):
    failed = [s for s in spans if s["attributes"].get("eval.passed") is False]
    errors = [s for s in spans if s["status"] == "ERROR"]
    checks = [s for s in spans if "eval.passed" in s["attributes"]]
    selected = failed or errors or checks
    return vote(
        "Reliability",
        "block" if failed else "review" if errors else "pass" if checks else "abstain",
        "Explicit outcome assertions failed."
        if failed
        else "Execution errors need recovery review."
        if errors
        else "Recorded outcome assertions passed."
        if checks
        else "No explicit outcome assertions were recorded.",
        [
            {
                "span_id": s["span_id"],
                "fact": f"status={s['status']}; eval.passed={s['attributes'].get('eval.passed', 'unrecorded')}",
            }
            for s in selected[:6]
        ],
    )


def evidence_quality(spans):
    evidence = [s for s in spans if "retrieval.current" in s["attributes"]]
    stale = [s for s in evidence if s["attributes"]["retrieval.current"] is False]
    return vote(
        "Evidence quality",
        "block" if stale else "pass" if evidence else "abstain",
        "Obsolete source metadata was recorded."
        if stale
        else "Retrieved sources are marked current; answer entailment is not assessed."
        if evidence
        else "No source freshness metadata; grounding cannot be inferred.",
        [
            {
                "span_id": s["span_id"],
                "fact": f"retrieval.current={s['attributes']['retrieval.current']}",
            }
            for s in (stale or evidence)[:6]
        ],
    )


def efficiency(spans):
    repeated = {}
    evidence = []
    for s in spans:
        tool = s["attributes"].get("tool.name")
        if tool and s["kind"] == 3:
            repeated.setdefault(tool, []).append(s)
        duration = (s["end_ns"] - s["start_ns"]) / 1e6
        if s["name"] == "model.generate" and duration > 5000:
            evidence.append(
                {
                    "span_id": s["span_id"],
                    "fact": f"Model duration {duration:.0f} ms exceeds the lab's 5000 ms review threshold.",
                }
            )
    for tool, calls in repeated.items():
        if len(calls) >= 3:
            evidence.append(
                {
                    "span_id": calls[-1]["span_id"],
                    "fact": f"{tool}: {len(calls)} client calls; review threshold is 3.",
                }
            )
    root = next((s for s in spans if s["parent_id"] is None), None)
    return vote(
        "Efficiency",
        "review" if evidence else "pass" if root else "abstain",
        "A configured lab efficiency threshold was exceeded."
        if evidence
        else "No configured threshold exceeded; this does not establish production efficiency."
        if root
        else "Partial trace has no root; end-to-end efficiency is unverified.",
        evidence
        or (
            [
                {
                    "span_id": root["span_id"],
                    "fact": f"Observed trace window: {summarize(spans)['duration_ms']} ms.",
                }
            ]
            if root
            else []
        ),
    )


ANALYZERS = (reliability, evidence_quality, efficiency)


def aggregate(votes):
    # A majority cannot overrule a blocking finding or missing analyzer evidence.
    verdicts = {v["verdict"] for v in votes}
    return next(v for v in ("block", "abstain", "review", "pass") if v in verdicts)


def review_trace(store, trace_id, analyzers=None):
    spans = store.spans(trace_id)
    if not spans:
        raise KeyError(trace_id)
    ids = {s["span_id"] for s in spans}
    votes = []
    for analyzer in analyzers or ANALYZERS:
        try:
            result = analyzer(spans)
            if result["verdict"] not in {"block", "abstain", "review", "pass"}:
                raise ValueError("Invalid verdict")
            if any(e["span_id"] not in ids for e in result["evidence"]):
                raise ValueError("Unsupported evidence reference")
            if result["verdict"] != "abstain" and not result["evidence"]:
                raise ValueError("Missing evidence")
            votes.append(result)
        except Exception:
            votes.append(
                vote(
                    getattr(analyzer, "__name__", "Analyzer"),
                    "abstain",
                    "Analyzer failed or returned unsupported evidence. Human review required.",
                    [],
                )
            )
    report = {
        "id": str(uuid.uuid4()),
        "created_at": time.time(),
        "trace_id": trace_id,
        "decision": aggregate(votes),
        "votes": votes,
        "disagreement": len({v["verdict"] for v in votes}) > 1,
        "limitations": "Three rule-based analyzers inspect recorded metadata. They are not independent AI experts, do not inspect hidden reasoning, and do not certify security or factual correctness. No tool is executed by this review.",
    }
    store.put("review_reports", report)
    return report
