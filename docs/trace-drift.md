# Collected-trace drift monitoring (v0.7)

Open **Performance & drift → Collected traces**. Select an exact root service and two nonoverlapping UTC time windows, then analyze. Operator permission is required to create a report; readers can inspect reports in their credential-bound tenant. Client tenant headers cannot select another tenant's data.

`POST /api/drift/traces` takes `service`, `reference_start`, `reference_end`, `current_start`, and `current_end` (Unix seconds). Windows must be ordered, span at most 31 days in total, and end at least five seconds ago. They include root start times at the lower bound and exclude the upper bound. A window over 256 root spans is rejected rather than silently sampled. This is on-demand monitoring, not a scheduled alerting service.

## Observations and coverage

Both windows are read in one SQLite snapshot. Traces with multiple roots, missing parents, reversed span duration, or a span ending beyond the selected window are excluded and recorded in report coverage. Parent coverage and a five-second age guard cannot prove that every span arrived; delayed telemetry can change later comparisons. Rootless traces cannot be assigned to this cohort and are not counted. Stored trace IDs must identify unique executions.

Each eligible trace contributes at most one observation per metric:

| Metric | Definition | Missing behavior |
| --- | --- | --- |
| Execution duration | Maximum received end minus minimum received start, in milliseconds | Structural exclusions appear in coverage |
| Reported tokens | Sum of input plus output tokens on usage/model-attributed spans | Requires both nonnegative finite token fields on each such span; absent/partial/invalid usage is missing |
| Tool error rate | Percentage of tool spans reporting ERROR within each trace | No observed tools is missing, not zero errors |
| Explicit retry calls | Number of tool spans with `tool.attempt > 1` | Every counted tool must have a positive integer attempt; unknown attempts make the observation missing |

Tool SERVER spans are excluded from the last two metrics to avoid counting both client and server sides of MCP calls. This convention requires caller/internal instrumentation; server-only tools have missing observations. Token totals are reported telemetry, not independently verified billing; instrumenters must avoid duplicate aggregate usage. Tool error rates are compared per trace, not as a single call-weighted global rate. Explicit retry calls do not infer unrecorded earlier attempts.

Reports show eligible counts, missing/invalid counts, tested sample sizes, means, histograms, KS distance, and adjusted p-values. Every metric stores its trace IDs and numeric observations for both windows; **Inspect source traces** opens the corresponding execution. These are saved snapshots; links show the current stored trace, which may subsequently change.

## Statistical interpretation

A metric is tested only with at least 30 usable observations in each window. Otherwise it is marked **Not enough evidence**, without a histogram or significance claim. Missing values are never imputed as zero. No-data reports are not healthy verdicts.

The test uses a two-sample KS distance, 399 seeded label permutations, and Bonferroni adjustment over metrics actually tested. A shift requires adjusted p < 0.05 and distance ≥ 0.2. Assumptions and limitations:

- Exchangeability is required; temporal dependence and recurring workload patterns can invalidate naive permutation inference.
- Correction covers the tested metrics in one report, not repeated monitoring over time.
- Changing model/prompt versions, traffic mix, sampling, or telemetry coverage can confound results. This release filters by root service, not those finer cohorts.
- Distribution shifts do not establish quality degradation, concept drift, or cause. Human labels and verified task outcomes belong to the next evaluation phase.

## Reproducible demonstration

With a local collector running and `AGENTSCOPE_EXPORT_TOKEN` privately set to a collector key:

```bash
.venv/bin/python examples/trace_drift_fixture.py
```

This ingests 60 **explicitly synthetic** traces via authenticated OTLP. It prints the service (`drift-lab-synthetic`) and exact window boundaries. Timestamps, durations, token counts and errors are authored fixtures, not measured model performance. Use the printed windows in the dashboard; defaults match if you run within the same UTC hour. Repeated runs add new traces and can eventually exceed the window cap.

Expected: 30 reference and 30 current observations per metric, four detected distribution shifts, and links to all underlying synthetic executions. An unpopulated service produces four insufficient-evidence results. Synthetic numeric-window scenarios remain available separately.
