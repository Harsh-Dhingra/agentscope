"""Metadata-only OTLP logs. Free-text bodies never enter durable storage."""

import base64
import hashlib
import json
from google.protobuf.json_format import ParseDict
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
)
from .privacy import safe_attributes
from .telemetry import attribute_value

MAX_RECORDS = 2000


def decode_logs(body: bytes, content_type: str) -> list[dict]:
    message = ExportLogsServiceRequest()
    if content_type == "application/x-protobuf":
        message.ParseFromString(body)
    else:
        payload = json.loads(body)
        for resource in payload.get("resourceLogs", []):
            for scope in resource.get("scopeLogs", []):
                for record in scope.get("logRecords", []):
                    for key in ("traceId", "spanId"):
                        if record.get(key):
                            record[key] = base64.b64encode(
                                bytes.fromhex(record[key])
                            ).decode()
        ParseDict(payload, message)
    records = []
    for resource in message.resource_logs:
        attrs = {a.key: attribute_value(a.value) for a in resource.resource.attributes}
        safe_resource = safe_attributes(attrs)
        # Cloud routing labels have fixed vocabularies; arbitrary account IDs are dropped.
        if attrs.get("cloud.provider") in {"aws", "gcp", "azure"}:
            safe_resource["cloud.provider"] = attrs["cloud.provider"]
        for scope in resource.scope_logs:
            for record in scope.log_records:
                if len(records) >= MAX_RECORDS:
                    raise ValueError("Too many log records")
                for value, size in ((record.trace_id, 16), (record.span_id, 8)):
                    if value and (len(value) != size or not any(value)):
                        raise ValueError("Invalid correlation ID")
                if record.span_id and not record.trace_id:
                    raise ValueError("Span ID requires trace ID")
                timestamp = record.time_unix_nano or record.observed_time_unix_nano
                if (
                    not 0 < timestamp <= 2**63 - 1
                    or not 0 <= record.severity_number <= 24
                ):
                    raise ValueError("Invalid timestamp or severity")
                item = {
                    "time_ns": timestamp,
                    "trace_id": record.trace_id.hex() or None,
                    "span_id": record.span_id.hex() or None,
                    "severity_number": record.severity_number,
                    "resource": safe_resource,
                    "attributes": safe_attributes(
                        {a.key: attribute_value(a.value) for a in record.attributes}
                    ),
                    "body_policy": "omitted",
                }
                # Hash only retained metadata, never customer content. Identical metadata
                # at the same timestamp intentionally collapses into one record.
                item["id"] = hashlib.sha256(
                    json.dumps(item, sort_keys=True, allow_nan=False).encode()
                ).hexdigest()
                records.append(item)
    return records
