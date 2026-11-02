"""OpenTelemetry instrumentation, redacted export, and OTLP decoding."""

from urllib.parse import urlparse
import httpx
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    SpanExporter,
    SpanExportResult,
    SimpleSpanProcessor,
)
from .privacy import safe_attributes, scrub


def attribute_value(value):
    kind = value.WhichOneof("value")
    return (
        getattr(value, kind)
        if kind in {"string_value", "bool_value", "int_value", "double_value"}
        else None
    )


def decode_otlp(request: ExportTraceServiceRequest) -> list[dict]:
    spans = []
    for resource in request.resource_spans:
        res = safe_attributes(
            {a.key: attribute_value(a.value) for a in resource.resource.attributes}
        )
        for scope in resource.scope_spans:
            for span in scope.spans:
                if (
                    len(span.trace_id) != 16
                    or len(span.span_id) != 8
                    or not any(span.trace_id)
                    or not any(span.span_id)
                ):
                    raise ValueError("Invalid trace/span ID")
                if span.parent_span_id and len(span.parent_span_id) != 8:
                    raise ValueError("Invalid parent span ID")
                if span.end_time_unix_nano < span.start_time_unix_nano:
                    raise ValueError("Span ends before it starts")
                spans.append(
                    {
                        "trace_id": span.trace_id.hex(),
                        "span_id": span.span_id.hex(),
                        "parent_id": span.parent_span_id.hex() or None,
                        "name": scrub(span.name),
                        "kind": span.kind,
                        "start_ns": span.start_time_unix_nano,
                        "end_ns": span.end_time_unix_nano,
                        "status": "ERROR"
                        if span.status.code == 2
                        else "OK"
                        if span.status.code == 1
                        else "UNSET",
                        "attributes": safe_attributes(
                            {a.key: attribute_value(a.value) for a in span.attributes}
                        ),
                        "resource": res,
                        "events": [
                            {
                                "name": scrub(e.name),
                                "attributes": safe_attributes(
                                    {
                                        a.key: attribute_value(a.value)
                                        for a in e.attributes
                                    }
                                ),
                            }
                            for e in span.events
                        ],
                        "links": [
                            {"trace_id": l.trace_id.hex(), "span_id": l.span_id.hex()}
                            for l in span.links
                        ],
                    }
                )
    if len(spans) > 2000:
        raise ValueError("Batch exceeds 2000 spans")
    return spans


def _attributes(destination, values):
    for key, value in safe_attributes(values).items():
        a = destination.add(key=key)
        if isinstance(value, bool):
            a.value.bool_value = value
        elif isinstance(value, int):
            a.value.int_value = value
        elif isinstance(value, float):
            a.value.double_value = value
        else:
            a.value.string_value = value


def encode_spans(spans) -> ExportTraceServiceRequest:
    request = ExportTraceServiceRequest()
    for source in spans:
        resource = request.resource_spans.add()
        _attributes(resource.resource.attributes, dict(source.resource.attributes))
        scope = resource.scope_spans.add()
        scope.scope.name = "agentscope.safe-exporter"
        span = scope.spans.add()
        span.trace_id = source.context.trace_id.to_bytes(16, "big")
        span.span_id = source.context.span_id.to_bytes(8, "big")
        if source.parent:
            span.parent_span_id = source.parent.span_id.to_bytes(8, "big")
        span.name = scrub(source.name)
        span.kind = source.kind.value + 1
        span.start_time_unix_nano, span.end_time_unix_nano = (
            source.start_time,
            source.end_time,
        )
        span.status.code = source.status.status_code.value
        _attributes(span.attributes, dict(source.attributes or {}))
        for event in source.events:
            e = span.events.add(name=scrub(event.name), time_unix_nano=event.timestamp)
            _attributes(e.attributes, dict(event.attributes or {}))
        for link in source.links:
            l = span.links.add(
                trace_id=link.context.trace_id.to_bytes(16, "big"),
                span_id=link.context.span_id.to_bytes(8, "big"),
            )
            _attributes(l.attributes, dict(link.attributes or {}))
    return request


class SafeExporter(SpanExporter):
    """Redact before storage/transport. HTTP export is explicit and best effort."""

    def __init__(
        self,
        store=None,
        endpoint=None,
        allow_remote=False,
        export_token=None,
        outbox_path=None,
        queue_max_batches=1000,
        queue_max_bytes=32 * 1024 * 1024,
    ):
        self.store, self.endpoint = store, endpoint
        self.export_token = export_token
        if endpoint:
            url = urlparse(endpoint)
            if url.username or url.password or url.scheme not in {"http", "https"}:
                raise ValueError("Use an HTTP(S) endpoint without embedded credentials")
            if not allow_remote and url.hostname not in {
                "127.0.0.1",
                "localhost",
                "::1",
            }:
                raise ValueError("Remote export requires allow_remote=True")
            if (
                export_token
                and url.hostname not in {"127.0.0.1", "localhost", "::1"}
                and url.scheme != "https"
            ):
                raise ValueError("Authenticated remote export requires HTTPS")
        self.delivery = None
        if outbox_path:
            if not endpoint or store is not None:
                raise ValueError(
                    "Durable export requires an endpoint and no direct store"
                )
            from .delivery import DurableDelivery

            self.delivery = DurableDelivery(
                outbox_path, endpoint, export_token, queue_max_batches, queue_max_bytes
            )
        self.failed_batches = 0

    def export(self, spans):
        request = encode_spans(spans)
        try:
            if self.delivery:
                self.delivery.enqueue(request.SerializeToString())
                return SpanExportResult.SUCCESS
            if self.store:
                self.store.ingest(decode_otlp(request))
            if self.endpoint:
                with httpx.Client(trust_env=False, timeout=3) as client:
                    response = client.post(
                        self.endpoint,
                        content=request.SerializeToString(),
                        headers={
                            "Content-Type": "application/x-protobuf",
                            **(
                                {"Authorization": "Bearer " + self.export_token}
                                if self.export_token
                                else {}
                            ),
                        },
                    )
                    response.raise_for_status()
            return SpanExportResult.SUCCESS
        except Exception:
            self.failed_batches += 1
            return SpanExportResult.FAILURE

    def force_flush(self, timeout_millis=30000):
        return self.delivery.flush(timeout_millis) if self.delivery else True

    def shutdown(self):
        if self.delivery:
            self.delivery.close()


def create_tracer(
    service="demo-agent",
    environment="local",
    store=None,
    endpoint=None,
    allow_remote=False,
    export_token=None,
    outbox_path=None,
    queue_max_batches=1000,
    queue_max_bytes=32 * 1024 * 1024,
):
    provider = TracerProvider(
        resource=Resource.create(
            {"service.name": service, "deployment.environment.name": environment}
        )
    )
    exporter = SafeExporter(
        store,
        endpoint,
        allow_remote,
        export_token,
        outbox_path,
        queue_max_batches,
        queue_max_bytes,
    )
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("agentscope", "0.7.1"), provider, exporter
