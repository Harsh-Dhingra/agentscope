"""Fail-closed attribute allowlist. Content capture is intentionally unsupported."""

import re

ALLOWED = frozenset(
    {
        "service.name",
        "deployment.environment.name",
        "agent.scenario",
        "agent.variant",
        "agent.runtime",
        "agent.role",
        "agent.outcome",
        "agent.run_id",
        "agent.step",
        "gen_ai.provider.name",
        "gen_ai.request.model",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "gen_ai.operation.name",
        "tool.name",
        "tool.attempt",
        "tool.result",
        "retrieval.document_id",
        "retrieval.policy_version",
        "retrieval.current",
        "eval.passed",
        "eval.name",
        "error.type",
        "exception.type",
        "mcp.method",
        "agentscope.dropped_attributes",
        "agent.protocol",
        "agent.cost_usd",
    }
)
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
TOKEN = re.compile(r"(?i)(bearer\s+\S+|(?:sk|ghp|gho)[-_][a-z0-9_-]{12,})")


def scrub(value: str) -> str:
    return TOKEN.sub("[REDACTED]", EMAIL.sub("[EMAIL]", value))[:256]


def safe_attributes(attributes: dict) -> dict:
    result = {}
    dropped = 0
    for key, value in attributes.items():
        if key not in ALLOWED or not isinstance(value, (str, bool, int, float)):
            dropped += 1
            continue
        result[key] = scrub(value) if isinstance(value, str) else value
    if dropped:
        result["agentscope.dropped_attributes"] = dropped
    return result
