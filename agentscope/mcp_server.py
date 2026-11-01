"""Real MCP stdio tool process with explicit W3C trace context propagation."""

import json
import os
from mcp.server.fastmcp import FastMCP
from opentelemetry.propagate import extract
from opentelemetry.trace import SpanKind
from .telemetry import create_tracer

mcp = FastMCP("AgentScope runbook tools")
tracer, provider, exporter = create_tracer(
    service="mcp-runbook-worker",
    endpoint=os.environ.get(
        "AGENTSCOPE_EXPORT_ENDPOINT", "http://127.0.0.1:8765/v1/traces"
    ),
)


@mcp.tool()
def lookup_runbook(current: bool = True, traceparent: str = "") -> str:
    """Return a synthetic runbook; traceparent links the caller's execution trace."""
    from .demo import runbook

    with tracer.start_as_current_span(
        "mcp.lookup_runbook",
        context=extract({"traceparent": traceparent}),
        kind=SpanKind.SERVER,
        attributes={
            "mcp.method": "tools/call",
            "tool.name": "runbook.server",
            "tool.result": "success",
        },
    ):
        return json.dumps(runbook(current))


if __name__ == "__main__":
    try:
        mcp.run(transport="stdio")
    finally:
        provider.shutdown()
