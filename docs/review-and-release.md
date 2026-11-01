# Phase 3: evidence review, replay, and local release control

## Review without unsupported consensus claims

Three independent functions analyze the same received trace:

- **Reliability:** explicit failed assertions block; execution errors require recovery review; missing assertions produce abstention.
- **Evidence quality:** an explicitly obsolete source blocks; current-source metadata passes only that freshness check; absent metadata produces abstention. This does not verify answer entailment.
- **Efficiency:** model spans over 5 seconds or at least three client calls to the same tool trigger review. These are configurable-in-code lab thresholds, not calibrated production SLOs. Server-side MCP spans are not counted as additional client attempts.

Each finding contains received span IDs. Missing/invalid evidence and analyzer exceptions become abstentions. Aggregation gives precedence to block, then abstain, then review, then pass. A majority cannot erase a block or an evidence gap. The report never executes a tool. These analyzers are deterministic rules, not three LLMs or autonomous domain experts.

## Reproduction and CI

The workbench maps a recorded built-in run back to its authored scenario and creates a new scripted execution with fresh trace IDs. It does not reconstruct external prompts or replay original model output. Arbitrary customer traces require a separately written, sanitized test.

```bash
python -m agentscope.cli replay --scenario stale_evidence --variant baseline --output data/failure.json
# Expected exit code: 1, with failed assertion evidence.
python -m agentscope.cli replay --scenario stale_evidence --variant guarded --output data/fix.json
# Expected exit code: 0.
python -m agentscope.cli check --variant guarded --output data/ci-regression.json
# All four authored cases; CI runs this command.
```

No running API, model service, or network access is needed for these scripted commands. All dependencies must already be installed.

## Controlled adaptation

The registry contains two immutable lab configurations: `baseline-v1` and `guarded-v2`. They select the actual implementation variants in `demo.py`: source filtering, bounded retries, and truthful fallback. The initial stable version is deliberately the flawed synthetic baseline so the improvement can be demonstrated.

An evaluation records four actual scripted runs, per-case assertions, export results, and a SHA-256 digest of the workload source plus configuration. The server computes the gate result. It accepts no client-supplied `eligible` flag.

A proposal can start a canary only if it passed, is unused, refers to the current deployment revision, has the same workload/config digest, and differs from the stable version. Explicit local approval sets a 20% candidate route. A hash of the supplied request ID provides stable bucket assignment. `POST /api/adapt/run` runs the selected version and records the actual outcome.

The dashboard's validation batch deliberately chooses five candidate and five stable request IDs. This covers both paths, but its 50/50 mix is not a sample of naturally occurring traffic. Five passing candidate probes are the minimum lab promotion gate; five cases are not statistical evidence of production safety. Promotion checks the source digest again and switches future local routed runs to the candidate.

An injected candidate availability failure records a failed span and canary outcome and removes the candidate from routing. A manual rollback cancels a canary or restores the previous stable version after promotion. All transitions leave a persisted event, and old proposals become invalid when the deployment revision changes.

## Important boundaries

This is a single-process, local workflow prototype using synthetic requests. It does not deploy or modify a remote model, Kubernetes service, Salesforce org, or cloud environment. It does not learn or fine-tune a model. Local approval buttons are not authenticated reviewer identities. Release events are inspectable application records, not tamper-evident audit storage.

External deployment needs durable workflow state transitions, separate reviewer authorization, actual traffic observations, held-out evaluations, failure budgets, rollback-compatible migrations, and deployment-specific adapters. The local database and process lock do not replace those requirements.
