"""Evidence-based diagnostics, not a general hallucination detector."""


def diagnose(spans):
    findings = []
    for span in spans:
        a = span["attributes"]
        if span["status"] == "ERROR":
            findings.append(
                {
                    "severity": "error",
                    "title": "Failed execution step",
                    "detail": f"{span['name']} reported {a.get('error.type', 'an error')}. Inspect its parent and downstream outcome.",
                    "span_id": span["span_id"],
                }
            )
        if a.get("retrieval.current") is False:
            findings.append(
                {
                    "severity": "warning",
                    "title": "Stale evidence retrieved",
                    "detail": "The document's explicit current-policy metadata is false. Verify the response against the effective policy.",
                    "span_id": span["span_id"],
                }
            )
        if a.get("eval.passed") is False:
            findings.append(
                {
                    "severity": "error",
                    "title": "Evaluation assertion failed",
                    "detail": a.get("eval.name", "An explicit assertion failed."),
                    "span_id": span["span_id"],
                }
            )
    tools = {}
    for s in spans:
        name = s["attributes"].get("tool.name")
        if name:
            tools.setdefault(name, []).append(s)
    for name, calls in tools.items():
        if len(calls) >= 3:
            findings.append(
                {
                    "severity": "warning",
                    "title": "Repeated tool calls",
                    "detail": f"{name} was invoked {len(calls)} times. Check retry policy or loop termination.",
                    "span_id": calls[-1]["span_id"],
                }
            )
    if spans:
        ids = {s["span_id"] for s in spans}
        for s in spans:
            if s["parent_id"] and s["parent_id"] not in ids:
                findings.append(
                    {
                        "severity": "info",
                        "title": "Parent span not received",
                        "detail": "This may be a partial trace, sampling, or an export still in flight.",
                        "span_id": s["span_id"],
                    }
                )
    return findings


def summarize(spans):
    roots = [s for s in spans if not s["parent_id"]]
    root = roots[0] if roots else spans[0]
    start = min(s["start_ns"] for s in spans)
    end = max(s["end_ns"] for s in spans)
    findings = diagnose(spans)
    attrs = root["attributes"]
    return {
        "trace_id": root["trace_id"],
        "name": root["name"],
        "started_ns": start,
        "duration_ms": round((end - start) / 1e6, 2),
        "span_count": len(spans),
        "error_count": sum(s["status"] == "ERROR" for s in spans),
        "finding_count": len(findings),
        "evaluation_failed": any(
            s["attributes"].get("eval.passed") is False for s in spans
        ),
        "runtime": attrs.get("agent.runtime", "external"),
        "scenario": attrs.get("agent.scenario", "external"),
        "variant": attrs.get("agent.variant", "—"),
        "outcome": attrs.get("agent.outcome", "unclassified"),
        "service": root["resource"].get("service.name", "unknown"),
        "tokens": sum(
            s["attributes"].get("gen_ai.usage.input_tokens", 0)
            + s["attributes"].get("gen_ai.usage.output_tokens", 0)
            for s in spans
        ),
        "has_usage": any("gen_ai.usage.input_tokens" in s["attributes"] for s in spans),
    }
