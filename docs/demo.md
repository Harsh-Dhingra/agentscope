# Fifteen-minute project showcase

This is the project track. Prepare the Salesforce “Servicing Agent” case separately.

## 0–2 minutes: problem and scope

Explain that API availability alone cannot show whether an agent used applicable evidence, retried a dependency excessively, or produced a supported answer. Introduce the incident-analysis example and the three things AgentScope connects: execution trace, diagnosis, and evaluation result.

State that this is a working local engineering lab with synthetic workloads. Do not claim production users or savings.

## 2–5 minutes: architecture

Walk through OTel instrumentation, source-side filtering, HTTP ingestion, SQLite, diagnosis, and the React UI. Explain why trace context must survive a process boundary and how the MCP example proves that property.

Describe SQLite and synchronous export as deliberate scope choices. Discuss what would need to change for enterprise scale.

## 5–9 minutes: live diagnosis

1. Choose **Stale evidence → Baseline → Scripted fixture → In process** and run it.
2. Open **Outcome & checks**. The answer says 90 days and the current-evidence assertion fails.
3. Open **Findings**, select stale evidence, and inspect the `retrieval.current=false` and `v1` metadata.
4. Repeat with **With controls**. The current runbook is `v3`, and the answer uses 30 days.
5. Run **Healthy → With controls → MCP**. Show the worker service under the client tool span.
6. If the local model is already warmed up, run **Local Ollama** and show reported token counts. Keep the deterministic fixture path as a backup, explicitly labeled.

## 9–12 minutes: evaluation and failure recovery

Open **Experiments** and run the comparison. Explain why the controlled timeout case escalates instead of asserting a status without evidence. Point out that execution errors remain visible even when an expected escalation passes evaluation.

Explain that 4/4 passing authored cases is a narrow regression result. Discuss a larger held-out dataset, independent human review, and stochastic repetitions before claims about model quality.

## 12–15 minutes: ownership and trade-offs

- Why OTel rather than a proprietary event schema?
- What is filtered before export, and what privacy problems remain?
- How does duplicate ingestion behave?
- What would happen if the collector went offline?
- How would you authenticate and isolate multiple tenants?
- How would you measure whether engineers diagnose incidents faster?

For business impact, propose a timed debugging study with the same incident set, equivalent participants, and success criteria. Present the plan as a future measurement; do not report unmeasured debugging-time reductions.

## Practice checklist

Be able to explain `telemetry.py`, `demo.py`, and the MCP integration test without reading a script. Make a small change yourself, add a meaningful test, and explain its effect. Keep a recording or screenshots of the measured run as a demo backup. State your use of AI development assistance accurately if asked.

## Expanded platform route (choose these instead of trying every feature)

Keep the live section to one coherent failure → evidence → fix → release story:

1. Run a stale-evidence baseline and inspect its failing assertion.
2. In **Review & replay**, select that trace and analyze it. Reliability and source freshness block; efficiency passes. Explain why a majority vote cannot erase evidence.
3. Click **Replay with controls** and open the passing trace. Show the equivalent CLI command.
4. In **Adapt & release**, evaluate the flawed baseline to show a blocked gate. Evaluate `guarded-v2` and approve its canary.
5. Run the validation batch, explain why it deliberately selects five requests per route, then promote. If showing recovery, roll back, reevaluate, restart the canary, and inject a candidate outage.
6. Use **Guardian** and **Performance & drift** as optional deeper dives, not extra screens to rush through.

Allow about 2 minutes for framing, 3 for architecture, 6 for the story, and 4 for decisions and limits. Be ready to explain why the first release has deterministic analyzers, what a statistical shift does and does not prove, and why fixture success cannot establish production quality.

Before the interview, make a change yourself: adjust one threshold or add a new synthetic fault with an independently meaningful assertion, run the test, and explain the failure it catches. Your ownership story should distinguish your decisions, AI-assisted implementation, tested behavior, and remaining work.
