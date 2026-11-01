# From observability lab to AI control platform

The product reference is a user-supplied marketing description of Imperative. It describes product categories and goals, not a complete functional specification. This document proposes independent, testable capabilities for AgentScope. It does not claim knowledge of Imperative's proprietary implementation or equivalent performance.

## What exists

The current local release provides trace ingestion, inspection, redacted export, rule-based diagnosis, synthetic evaluations, a LangGraph workload, a real MCP subprocess boundary, and actual local-model inference. It is the foundation for the platform, not the full platform.

## Proposed modules and acceptance criteria

| Module | User problem | Concrete capability | Acceptance evidence | Status |
|---|---|---|---|---|
| Observe | Cannot reconstruct an agent run | OTLP traces, service attribution, parent/child spans, model usage and tool errors | Trace from the application and MCP worker joins correctly | Implemented locally |
| Evaluate | Cannot tell whether a change fixed a failure | Versioned datasets, explicit assertions, baseline/candidate reports | Same fixture case fails before and passes after a controlled change | Small synthetic suite implemented |
| Performance | Quality or resources change silently | Model/prompt/retriever version registry; quality, latency, token, error and cost trends | Inject a known change and identify its time/version with a stable baseline | Planned |
| Drift | Production differs from reference behavior | Reference windows, distribution tests, minimum sample size, segmentation, effect size and alert review | Known shift detected; stationary controls stay within calibrated false-alarm bounds | Planned |
| Guardian | Agent invokes unsafe or unauthorized operations | Authenticated tool gateway, allowlists, per-action policy, budget/deadline limits, approval-required actions | Unauthorized write is denied before execution; permitted write remains functional | Planned; demo retry limits only |
| IDE | Developers cannot reproduce production failures | CLI/CI replay, dataset promotion from redacted traces, local run inspector, editor deep links | A sanitized failing trace becomes a reproducible test and blocks a bad change in CI | CI and examples exist; full workflow planned |
| Adapt | Teams cannot safely change a failing system | Versioned prompt/config proposals, offline evaluation, reviewer approval, canary rollout and rollback | Candidate passes gates, controlled rollout exposes a regression, rollback restores prior version | Planned |
| Expert review | A single diagnosis is brittle | Bounded independent analyzers with structured evidence; deterministic decision policy | Disagreement, missing evidence, and analyzer failure are visible; unsupported action is refused | Planned |
| Control plane | Multiple teams need governed operations | Authentication, tenancy, RBAC, audit events, model registry, quotas, secrets, retention | Tenant isolation and authorization tests; restore/deletion exercises | Planned |
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

### Phase 1: interview-ready observability foundation

Finish and publish the current working local implementation, tests, measured fixture report, architectural decisions and demo script. Practice explaining the code and limitations. Success: another developer can clone, run a failure, inspect its cause, change the controls and reproduce the comparison.

### Phase 2: performance and drift

Add model/config version metadata, reference and current datasets, a small set of calibrated detectors, and an alert inbox. Success: seeded shifts are detected with reported sample counts/effect sizes and stationary controls are evaluated for false alarms.

### Phase 3: controlled protection and expert review

Add a tool gateway with explicit authorization and deterministic policies, three structured analyzers, disagreement handling and review. Success: a denied action does not reach the target system, while a valid action completes exactly once under retry.

### Phase 4: adaptation and enterprise deployment

Add reviewed configuration proposals, canaries and rollback; then authenticated collectors, tenancy, scalable storage, queues and real hybrid deployment. Success criteria include isolation, recovery, deployment reproducibility and measured operational overhead.

No phase duration is promised before learning the interview deadline, deployment constraints and expected depth. All features should be marked implemented, simulated or planned in the UI/documentation.

## Keep the interview tracks distinct

The AgentScope showcase explains what was actually built, why, trade-offs, measured tests, and remaining production work. The Servicing Agent case demonstrates discovery, scope, KPIs, solution design and stakeholder judgment. AgentScope can inform the case's monitoring strategy without being presented as the whole servicing solution.
