# Data boundaries

## What is recorded

Trace and span identifiers, parentage, timing, status, links, named service/environment metadata, and a small allowlist of typed attributes. Demo outcomes include the answer to a fixed synthetic incident question in the separate runs table.

The bundled exporter excludes raw prompts, completions, arbitrary tool payloads, and exception messages before constructing the OTLP request. Unknown attributes are dropped; a counter records how many were excluded. The collector applies the same attribute filter on receipt.

Known email and token patterns are scrubbed from permitted strings. This is defense in depth, not a comprehensive PII classifier. Attribute values, span names, and event names must be controlled metadata rather than user content. An attacker can encode information in any allowed string; this lab does not claim to prevent all data exfiltration.

## What local means here

The default exporter only accepts loopback destinations. Local model calls go to configured loopback Ollama or the Docker host bridge, with no hosted fallback. The demo disables inherited LangSmith tracing flags. Frontend assets are bundled locally and use system fonts.

Dependencies and model weights need to be downloaded during setup. Ollama is a separate service with its own configuration. For an offline guarantee, configure all components, pre-provision dependencies, block runtime egress in an isolated environment, and capture evidence of attempted outbound connections. This project does not yet have that deployment-level verification.

## Incoming third-party traces

Collector-side filtering cannot undo data that already crossed a network boundary. If an external SDK sends raw prompts or secrets, it may already have exposed them before AgentScope drops the attributes. Apply filtering at the source, protect the transport, and avoid logging unfiltered request bodies in proxies.

## Local service protection

Native startup binds the API to loopback. Compose publishes only to host loopback. Host header checks reduce DNS-rebinding exposure, and unrelated browser origins cannot submit mutations. The default mode additionally requires local credentials, binds each credential to a tenant, and checks operation permissions. Browser writes require a session CSRF token and exact same-origin checks. See [access control](access-control.md). This remains a local lab; do not publish its API to the internet or ingest private production data.

## Production additions

Enterprise identity federation; ingestion quotas; TLS; encryption-at-rest configuration; separate key management; explicit retention/deletion; authenticated resource attribution; tamper-evident audit storage; safe export policy; incident response and backup/recovery procedures. None is implied by the word “local.”
