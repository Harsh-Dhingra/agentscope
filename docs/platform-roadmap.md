# From observability lab to AI control platform

The product reference is a user-supplied marketing description of Imperative. It describes product categories and goals, not a complete functional specification. This document proposes independent, testable capabilities for AgentScope. It does not claim knowledge of Imperative's proprietary implementation or equivalent performance.

## What exists

The current local release provides trace ingestion, inspection, redacted export, rule-based diagnosis, synthetic evaluations, a LangGraph workload, a real MCP subprocess boundary, actual local-model inference, numeric drift analysis, a synthetic tool policy gateway, bounded trace review, CLI replay, and local configuration release control. It is the foundation for the platform, not the full platform.

## Proposed modules and acceptance criteria

| Module | User problem | Concrete capability | Acceptance evidence | Status |
|---|---|---|---|---|
| Observe | Cannot reconstruct an agent run | OTLP traces, service attribution, parent/child spans, model usage and tool errors | Trace from the application and MCP worker joins correctly | Implemented locally |
| Evaluate | Cannot tell whether a change fixed a failure | Versioned datasets, explicit assertions, baseline/candidate reports | Same fixture case fails before and passes after a controlled change | Small synthetic suite implemented |
| Performance | Quality or resources change silently | Model/prompt/retriever version registry; quality, latency, token, error and cost trends | Inject a known change and identify its time/version with a stable baseline | Trace timing/tokens and lab configuration versions implemented; cost attribution and population trends planned |
| Drift | Production differs from reference behavior | Reference windows, distribution tests, minimum sample size, segmentation, effect size and alert review | Known shift detected; stationary controls stay within calibrated false-alarm bounds | Numeric window API and charts implemented; production calibration and segmentation planned |
| Guardian | Agent invokes unsafe or unauthorized operations | Authenticated tool gateway, allowlists, per-action policy, budget/deadline limits, approval-required actions | Unauthorized write is denied before execution; permitted write remains functional | Synthetic policy gateway, approval and idempotency implemented; local requester/reviewer identity implemented; enterprise federation planned |
| IDE | Developers cannot reproduce production failures | CLI/CI replay, dataset promotion from redacted traces, local run inspector, editor deep links | A sanitized failing trace becomes a reproducible test and blocks a bad change in CI | Built-in scenario replay and CLI/CI gates implemented; external sanitized dataset authoring planned |
| Adapt | Teams cannot safely change a failing system | Versioned prompt/config proposals, offline evaluation, reviewer approval, canary rollout and rollback | Candidate passes gates, controlled rollout exposes a regression, rollback restores prior version | Local fixture version registry, gates, canary routing and rollback implemented; external deployment planned |
| Expert review | A single diagnosis is brittle | Bounded independent analyzers with structured evidence; deterministic decision policy | Disagreement, missing evidence, and analyzer failure are visible; unsupported action is refused | Three bounded rule-based analyzers and deterministic abstention/aggregation implemented; model-based panel evaluation planned |
| Control plane | Multiple teams need governed operations | Authentication, tenancy, RBAC, audit events, model registry, quotas, secrets, retention | Tenant isolation and authorization tests; restore/deletion exercises | Local identity, tenant databases, roles and mutation audit implemented; durability and enterprise identity planned |
| Hybrid deployment | Workloads span local and cloud boundaries | Authenticated collectors, TLS, durable export queues, trace propagation, topology and egress policy | Trace survives a real two-environment run and a controlled network interruption | Process boundary tested; cloud topology planned |

## Define five monitoring categories explicitly

The source says “five different types of drift” but does not name them. The following is our proposed taxonomy, not a claim about the source product:

1. **Input distribution shift:** changes in language, intent mix, input length, or approved structured features. Uses a reference dataset and sufficient current samples.
2. **Prediction/output shift:** changes in response length, refusal rate, tool-choice distribution, or structured output categories. This is not automatically evidence of worse quality.
3. **Quality/performance degradation:** changes in labeled task success, groundedness, human ratings, or domain metrics. Requires reliable outcomes or reviewed labels; unlabeled telemetry cannot establish all of these.
4. **Knowledge/retrieval change:** source freshness, index/version changes, coverage, retrieval relevance, and citation support. Some are deterministic freshness checks; others need reviewed query-document relevance.
5. **Operational behavior change:** tool error mix, retries, latency, token usage, dependency failures, and measured/estimated costs. These are operational shifts, not necessarily statistical model drift.

Concept drift describes a change in the relationship between inputs and the correct target. Detecting it reliably generally requires outcomes/labels or carefully validated proxies. Do not label every distribution shift as concept drift.

Implement one or two well-defined detectors first. Define window size, reference population, missing-data handling, thresholds, multiple-testing treatment, effect-size reporting, and alert ownership. Validate false positives on stationary control windows before automatic remediation.

## “Pluginless” needs a boundary

Gateway logs, network/service metrics, and existing telemetry can be collected with little or no application-code change. Detailed internal tool/delegation spans require framework instrumentation, existing spans, a proxy-aware integration, or application hooks. Encrypted traffic and a final response do not reveal arbitrary internal agent state or hidden model reasoning.

Offer two explicit collection modes: low-touch gateway/service monitoring and deeper instrumented agent tracing. State the visibility each mode provides. “Zero contact with models” does not grant control over model behavior or access to invisible internals.

## Expert systems without unsupported guarantees

Begin with three bounded roles: reliability analyzer, security-policy analyzer, and performance analyzer. Each returns a structured finding with trace IDs, evidence, confidence/rationale summary, and a proposed action. A deterministic policy engine decides whether the evidence permits an action, requires review, or requires abstention.

Consensus among models can be correlated and wrong. Evaluate the panel against a single-analyzer baseline, measure false positives, latency and cost, and avoid multiplying agents before the measurements justify it. Never promise perfect decisions, complete protection, or regulatory compliance from model consensus.

## Build phases

### Phase 1 — shipped: observability foundation

Finish and publish the current working local implementation, tests, measured fixture report, architectural decisions and demo script. Practice explaining the code and limitations. Success: another developer can clone, run a failure, inspect its cause, change the controls and reproduce the comparison.

### Phase 2 — shipped: drift and tool policy

Numeric comparison API and charts, sample-size validation, effect size, permutation tests, correction across metrics, and seeded controls. Synthetic tool gateway checks scope and role, requires explicit review for a restart, and proves one local effect under concurrent approval.

### Phase 3 — shipped: review, replay, and release control

Three evidence analyzers, disagreement and abstention, built-in test replay, CLI regression gates, versioned configurations, a digest-bound evaluation, local canary routing, minimum sample gates, and promotion/rollback. The release loop uses actual scripted executions; identities and workloads remain synthetic.

### Phase 4a — implemented: local identity and access

Credential-bound tenant databases, operator/reviewer/viewer/collector roles, revocable sessions, CSRF protection, separate requester/reviewer principals, and tenant mutation audit records. See [access control](access-control.md). This does not provide enterprise SSO or distributed resource isolation.

### Phase 4b — partially implemented: operational durability

v0.5 implements an optional durable sender outbox, restart recovery, bounded admission, retry/backoff, quarantine and delivery counters. See [durable delivery](durable-delivery.md). Retention and deletion, audited quarantine recovery, distributed collector queues, and tamper-evident audit records remain. Define and test authorization boundaries before connecting real tools. Replace local locks with durable workflow transitions for distributed operation.

### Phase 5 — next: real integrations and calibrated intelligence

Run an authenticated collector across a real cloud/local boundary, connect a narrowly scoped external tool, expand held-out evaluations, calibrate drift false alarms on representative data, compare model-based analyzers against the deterministic baseline, and benchmark cost, overhead and diagnosis time. Add Salesforce/Snowflake adapters only when a concrete data/access contract and use case justify them.

No phase duration is promised before learning the interview deadline, deployment constraints and expected depth. All features should be marked implemented, simulated or planned in the UI/documentation.

## Keep the interview tracks distinct

The AgentScope showcase explains what was actually built, why, trade-offs, measured tests, and remaining production work. The Servicing Agent case demonstrates discovery, scope, KPIs, solution design and stakeholder judgment. AgentScope can inform the case's monitoring strategy without being presented as the whole servicing solution.
