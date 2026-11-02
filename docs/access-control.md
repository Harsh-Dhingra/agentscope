# Local identity and access

v0.4 requires authentication by default. This is a local credential registry, not enterprise SSO or a production multi-tenant service.

## Provision and sign in

Run `make init-access` after `make setup`. The CLI creates operator, reviewer, viewer, and collector credentials for the `local` tenant in `data/access-keys.json`. The file is created with mode 0600, is ignored by Git, and must remain private. Credentials expire after 30 days by default. Initialization refuses to overwrite an existing output file.

Paste the operator key into the local sign-in screen. Use the reviewer key in a separate sign-in to approve requests. The browser stores a revocable HttpOnly, SameSite=Strict session cookie, not the access key in local storage. Sessions expire after eight hours and cannot outlive their source credential. HTTPS sets Secure; loopback HTTP supports local development.

For another tenant:

```bash
.venv/bin/python -m agentscope.identity init --tenant team-b --output data/team-b-keys.json
```

Issue an individual role or revoke a credential using its non-secret key ID:

```bash
.venv/bin/python -m agentscope.identity issue --tenant local --subject alice --role operator --output data/alice-key.json
.venv/bin/python -m agentscope.identity revoke --key-id KEY_ID
```

The global `--db` option or `AGENTSCOPE_IDENTITY_DB` selects the identity database. If you customize the application database path, explicitly configure the same identity database for the API and CLI. Revocation takes effect on the next API/session request. Keys and session secrets are stored as SHA-256 digests. Keep private output files out of screenshots, source control, and trace metadata.

## Permissions and isolation

| Role | Permissions |
| --- | --- |
| Viewer | Read tenant traces, reports, and access audit |
| Operator | Read, run workloads, ingest, submit synthetic tool requests, propose releases |
| Reviewer | Read, approve another subject's requests, promote, roll back |
| Collector | POST telemetry only; no dashboard login or reads |

The server selects storage from the authenticated credential's tenant. Client headers and trace resource attributes cannot override it. Each tenant uses a separate SQLite file with a hashed filename; the local tenant preserves the legacy database. This is an application access boundary within one process, not OS-level or resource isolation.

Approvals require a reviewer whose subject differs from the request creator, even when that creator has another role/key. Legacy proposals without a creator must be recreated. Locally issued subjects do not prove that two different humans hold the keys.

## API and instrumentation

Send `Authorization: Bearer KEY` for API clients. Set `AGENTSCOPE_API_KEY` to an operator key for `examples/evaluate.py`; set `AGENTSCOPE_EXPORT_TOKEN` to a collector key for `examples/instrument.py`. The bundled exporter sends credentials in a header and rejects credentialed remote HTTP endpoints without TLS. Remote export still requires explicit opt-in.

MCP demo runs receive a short-lived collector credential for their tenant. The parent revokes it after the run, including on errors. Browser mutations require both exact same-origin validation and a CSRF token. Login has a bounded process-local throttle; it is not a distributed abuse-control service.

## Audit and limits

Tenant mutation records contain subject, role, tenant, method, route template, status, and timestamp. They exclude request bodies, raw paths/IDs, query strings, credentials, and CSRF tokens. The audit is inspectable application data, not tamper-evident storage or a transactionally complete compliance log. Anonymous rejected traffic is not a tenant audit trail.

`AGENTSCOPE_AUTH_MODE=development` explicitly bypasses authentication and reviewer separation for disposable local development. Never use it for shared or exposed environments. The default remains `required`; invalid modes fail startup.

Remaining work: enterprise identity federation, scoped administrative lifecycle, distributed throttling, quotas, retention/deletion, durable queues, transactional workflow/audit transitions, encryption/key management, tested backup/restore, and a verified hybrid TLS deployment. Keep this lab on loopback and use synthetic data.
