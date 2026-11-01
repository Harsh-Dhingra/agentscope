# Phase 2: measurable shifts and bounded tool execution

## Drift analysis

`POST /api/drift/analyze` accepts up to six named numeric metrics, each with a reference and current sample of 30–256 finite values. Categories are input, output, quality, retrieval, and operational. These are our monitoring categories, not claims about another vendor's implementation.

Each comparison reports a two-sample empirical KS distance, a Monte Carlo label-permutation p-value (399 permutations, fixed seed, add-one correction), and Bonferroni adjustment across that request's metrics. An alert requires adjusted p < alpha and distance ≥ minimum effect. Defaults are 0.05 and 0.2. Histograms and summary statistics are saved; raw arrays are not stored in reports.

Observations must be exchangeable under the null. Repeated measurements, seasonality, correlated time series, repeated monitoring, and population changes require a stronger study design and calibration. Correction within one request does not control false alarms across repeated requests. Five fixture categories do not mean five universally solved drift problems. A shift does not prove degradation or cause; concept drift needs target/outcome information.

The UI includes seeded stationary, latency-spike, reviewed-quality-regression, and knowledge-aging scenarios. Tests verify the stationary fixture has no alert and the three shifts localize to their intended category. This is reproducibility evidence, not a population-level false-positive estimate.

## Guardian gateway

`POST /api/guardian/demo` selects a server-defined scenario. The server chooses the principal and tool; the client cannot submit an arbitrary role or executable command.

Policy order: permitted resource → tool allowlist → operator requirement → explicit approval. Read-only health inspection is allowed; log export and namespace deletion are denied; worker restart requires operator status plus review. The executor repeats the checks before touching state.

The synthetic worker's restart counter and idempotency result are updated in the same SQLite transaction. Reusing a key for a different principal/tool/target is rejected. Repeated or concurrent approval produces one counter increment. The decision record persists the policy result and whether execution occurred.

This exactly-once effect is limited to a local SQLite transaction. Real remote tools would need downstream idempotency and recovery/outbox design. Demo principals are not authenticated users; the approve endpoint has no reviewer identity. Connect real services only after authentication, authorization, approval separation, durable auditing, and resource-specific policy are implemented.

## Walkthrough

1. Open **Performance & drift**, run **Stationary control**, then **Latency spike**. Read sample counts, effect size, and adjusted p.
2. Open **Guardian** and submit **Unauthorized restart**. Inspect `Executed: No`.
3. Submit **Restart needs approval**. It remains unexecuted until the review button is clicked.
4. Approve it. Inspect the synthetic restart counter and compare with the automated concurrency test.
