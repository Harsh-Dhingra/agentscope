"""Run with the collector listening on localhost:8765."""

import time
from agentscope.telemetry import create_tracer

tracer, provider, exporter = create_tracer(
    service="external-python-agent", endpoint="http://127.0.0.1:8765/v1/traces"
)
with tracer.start_as_current_span(
    "agent.run", attributes={"agent.runtime": "external", "agent.role": "coordinator"}
):
    with tracer.start_as_current_span(
        "researcher", attributes={"agent.role": "researcher"}
    ):
        with tracer.start_as_current_span(
            "tool.search",
            attributes={
                "tool.name": "search",
                "input.value": "This content must never be exported",
            },
        ):
            time.sleep(0.05)
provider.shutdown()
if exporter.failed_batches:
    raise SystemExit("Trace export failed; start the collector first")
print("Exported a redacted, nested trace to AgentScope")
