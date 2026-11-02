"""Persist redacted spans through collector outages; rerun with --drain-only to recover."""

import argparse
import json
import os
from agentscope.telemetry import create_tracer

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--drain-only", action="store_true")
parser.add_argument("--outbox", default="data/export-outbox.db")
parser.add_argument("--timeout-ms", type=int, default=5000)
args = parser.parse_args()
tracer, provider, exporter = create_tracer(
    service="durable-example",
    endpoint="http://127.0.0.1:8765/v1/traces",
    export_token=os.environ["AGENTSCOPE_EXPORT_TOKEN"],
    outbox_path=args.outbox,
)
try:
    if not args.drain_only:
        with tracer.start_as_current_span("durable.example") as span:
            span.set_attribute(
                "input.value", "Synthetic raw content excluded before disk"
            )
            span.set_attribute("tool.name", "example")
    drained = exporter.force_flush(args.timeout_ms)
    print(json.dumps(exporter.delivery.status(), indent=2))
finally:
    provider.shutdown()
if exporter.failed_batches:
    raise SystemExit(
        "Batch was not accepted; inspect disk availability and queue capacity."
    )
if not drained:
    raise SystemExit(
        "Delivery incomplete; outbox retained. Restore the collector and rerun with --drain-only."
    )
print("Outbox fully delivered.")
