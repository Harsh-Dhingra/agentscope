"""Ingest 60 explicitly synthetic traces for the collected-window walkthrough."""

import json
import os
import time
import uuid
import httpx
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)

end = int(time.time() // 3600) * 3600
message = ExportTraceServiceRequest()
for current in [False, True]:
    for i in range(30):
        resource = message.resource_spans.add()
        resource.resource.attributes.add(
            key="service.name"
        ).value.string_value = "drift-lab-synthetic"
        scope = resource.scope_spans.add()
        trace = uuid.uuid4().bytes
        start = int((end - (3500 if current else 7100) + i * 2) * 1e9)
        for sid, name, attrs in [
            (1, "synthetic.run", {}),
            (
                2,
                "synthetic.lookup",
                {"tool.name": "fixture", "tool.attempt": 2 if current else 1},
            ),
            (
                3,
                "synthetic.model",
                {
                    "gen_ai.request.model": "synthetic-no-inference",
                    "gen_ai.usage.input_tokens": 200 if current else 100,
                    "gen_ai.usage.output_tokens": 50,
                },
            ),
        ]:
            span = scope.spans.add(
                trace_id=trace,
                span_id=sid.to_bytes(8, "big"),
                name=name,
                kind=1 if sid == 1 else 3,
                start_time_unix_nano=start,
                end_time_unix_nano=start + (500000000 if current else 100000000),
            )
            if sid != 1:
                span.parent_span_id = (1).to_bytes(8, "big")
            span.status.code = 2 if current and sid == 2 else 1
            for key, value in attrs.items():
                a = span.attributes.add(key=key)
                if isinstance(value, int):
                    a.value.int_value = value
                else:
                    a.value.string_value = value
with httpx.Client(trust_env=False) as client:
    response = client.post(
        "http://127.0.0.1:8765/v1/traces",
        content=message.SerializeToString(),
        headers={
            "Content-Type": "application/x-protobuf",
            "Authorization": "Bearer " + os.environ["AGENTSCOPE_EXPORT_TOKEN"],
        },
    )
    response.raise_for_status()
print(
    json.dumps(
        {
            "service": "drift-lab-synthetic",
            "reference_start": end - 7200,
            "reference_end": end - 3600,
            "current_start": end - 3600,
            "current_end": end,
            "note": "60 synthetic traces; timestamps, tokens, latency and failures are authored fixtures, not measured model performance.",
        },
        indent=2,
    )
)
