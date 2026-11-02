import { useEffect, useState } from "react";
import {
  GitBranch,
  FlaskConical,
  Play,
  RotateCcw,
  ShieldCheck,
  Users,
  ArrowUpRight,
  LoaderCircle,
  Check,
  CircleAlert,
} from "lucide-react";
import { request } from "./http";

type Trace = {
  trace_id: string;
  scenario: string;
  variant: string;
  runtime: string;
  name: string;
};
type Review = {
  id: string;
  trace_id: string;
  decision: string;
  disagreement: boolean;
  votes: {
    role: string;
    verdict: string;
    summary: string;
    method: string;
    evidence: { span_id: string; fact: string }[];
  }[];
  limitations: string;
};
type Replay = {
  id: string;
  source_trace_id: string;
  replay_trace_id: string;
  scenario: string;
  variant: string;
  passed: boolean;
  mode: string;
};
const badge = (value: string) =>
  value === "pass" || value === "promoted"
    ? "success"
    : value === "block" || value === "rolled_back"
      ? "danger"
      : "warning";

export function ReviewPanel({
  inspect,
  canOperate = true,
}: {
  inspect: (id: string) => void;
  canOperate?: boolean;
}) {
  const [traces, setTraces] = useState<Trace[]>([]),
    [selected, setSelected] = useState(""),
    [reports, setReports] = useState<Review[]>([]),
    [replays, setReplays] = useState<Replay[]>([]),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function refresh() {
    const [t, r, c] = await Promise.all([
      request<Trace[]>("/traces"),
      request<Review[]>("/reviews"),
      request<Replay[]>("/replays"),
    ]);
    setTraces(t);
    setReports(r);
    setReplays(c);
    setSelected((s) => s || t[0]?.trace_id || "");
  }
  useEffect(() => {
    void refresh().catch((e) => setError(String(e)));
  }, []);
  async function run(path: string) {
    setBusy(true);
    setError("");
    try {
      await request(path, { trace_id: selected });
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  const report = reports.find((r) => r.trace_id === selected),
    trace = traces.find((t) => t.trace_id === selected);
  const scenario =
    trace &&
    ["healthy", "stale_evidence", "tool_timeout", "retry_loop"].includes(
      trace.scenario,
    )
      ? trace.scenario
      : null;
  return (
    <>
      <section className="platform-intro">
        <div>
          <span className="pill neutral">REVIEW / REPLAY</span>
          <h2>Every recommendation needs evidence.</h2>
          <p>
            Three bounded analyzers inspect reliability, source freshness, and
            efficiency. A deterministic decision rule preserves blocking
            findings and abstains when evidence is missing.
          </p>
        </div>
        <div className="platform-actions">
          <label>
            Trace to review
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
            >
              {!traces.length && <option value="">Run a workload first</option>}
              {traces.map((t) => (
                <option key={t.trace_id} value={t.trace_id}>
                  {t.scenario} · {t.variant} · {t.trace_id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          <button
            className="primary"
            disabled={busy || !canOperate || !selected}
            onClick={() => void run("/reviews")}
          >
            {busy ? (
              <LoaderCircle size={16} className="spin" />
            ) : (
              <Users size={16} />
            )}{" "}
            Analyze trace
          </button>
        </div>
      </section>
      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}
      {report ? (
        <>
          <div className="decision-summary">
            <div>
              <span className={"pill " + badge(report.decision)}>
                {report.decision === "pass"
                  ? "Checks passed"
                  : report.decision === "block"
                    ? "Blocking evidence"
                    : report.decision === "abstain"
                      ? "Insufficient evidence"
                      : "Review required"}
              </span>
              <strong>
                {report.disagreement
                  ? "Different findings remain visible"
                  : "Analyzers agree within their scope"}
              </strong>
              <p>
                No majority vote can override a blocking finding. Missing
                evidence never becomes a pass.
              </p>
            </div>
            <button
              className="secondary"
              onClick={() => inspect(report.trace_id)}
            >
              Inspect source trace <ArrowUpRight size={14} />
            </button>
          </div>
          <div className="expert-grid">
            {report.votes.map((v) => (
              <section className="expert-card" key={v.role}>
                <div className="expert-head">
                  <Users size={19} />
                  <span className={"pill " + badge(v.verdict)}>
                    {v.verdict}
                  </span>
                </div>
                <h3>{v.role}</h3>
                <p>{v.summary}</p>
                <div className="expert-evidence">
                  {v.evidence.length ? (
                    v.evidence.map((e, i) => (
                      <div key={i}>
                        <code>{e.span_id}</code>
                        <p>{e.fact}</p>
                      </div>
                    ))
                  ) : (
                    <p>No supporting evidence available.</p>
                  )}
                </div>
                <small>{v.method}</small>
              </section>
            ))}
          </div>
          <p className="method-note">{report.limitations}</p>
        </>
      ) : (
        <div className="empty">
          <Users size={30} />
          <strong>No review for this trace yet</strong>
          <p>
            Analyze a recorded execution to inspect the evidence behind each
            finding.
          </p>
        </div>
      )}
      <section className="replay-workbench">
        <div>
          <span className="eyebrow">DEVELOPER WORKBENCH</span>
          <h2>Turn a failure into a regression check.</h2>
          <p>
            Replay the selected built-in scenario using the controlled
            implementation. The new run has its own trace and assertions.
          </p>
          {scenario && (
            <pre>
              <code>
                python -m agentscope.cli replay --scenario {scenario} --variant
                guarded
              </code>
            </pre>
          )}
        </div>
        <button
          className="primary"
          disabled={busy || !canOperate || !scenario}
          onClick={() => void run("/replays")}
        >
          <Play size={16} /> Replay with controls
        </button>
      </section>
      {replays.length > 0 && (
        <section className="policy-events">
          <div className="panel-head">
            <h2>Replay history</h2>
            <span className="micro">SYNTHETIC CASES ONLY</span>
          </div>
          {replays.slice(0, 8).map((c) => (
            <article className="replay-row" key={c.id}>
              <span className={"pill " + (c.passed ? "success" : "danger")}>
                {c.passed ? "Passed" : "Failed"}
              </span>
              <div>
                <strong>{c.scenario.replaceAll("_", " ")}</strong>
                <small>
                  {c.source_trace_id.slice(0, 8)} →{" "}
                  {c.replay_trace_id.slice(0, 8)} · {c.variant}
                </small>
              </div>
              <button
                className="secondary"
                onClick={() => inspect(c.replay_trace_id)}
              >
                Open trace <ArrowUpRight size={14} />
              </button>
            </article>
          ))}
        </section>
      )}
      <div className="method-note">
        <strong>Replay boundary</strong>
        <p>
          Raw prompts are not stored, so arbitrary customer interactions cannot
          be reconstructed. This workbench replays authored synthetic cases.
          External traces need a separately authored, sanitized test before
          entering a regression dataset.
        </p>
      </div>
    </>
  );
}

type Proposal = {
  id: string;
  candidate: string;
  created_by?: string;
  approved_by?: string;
  based_on_revision: number;
  eligible: boolean;
  status: string;
  code_digest: string;
  gates: { name: string; passed: boolean }[];
  rows: { passed: boolean }[];
};
type Deployment = {
  revision: number;
  stable: string;
  candidate: string | null;
  candidate_percent: number;
  previous: string | null;
};
type ReleaseData = {
  state: Deployment;
  versions: {
    id: string;
    source_filter: string;
    retry_budget: number;
    fallback: string;
  }[];
  proposals: Proposal[];
  events: {
    id: string;
    kind: string;
    created_at: number;
    stable?: string;
    candidate?: string;
    reason?: string;
    eligible?: boolean;
  }[];
  runs: {
    id: string;
    trace_id: string;
    version: string;
    route: string;
    scenario: string;
    passed: boolean;
    injected_outage: boolean;
  }[];
  candidate_samples: number;
  minimum_samples: number;
};

export function AdaptPanel({
  inspect,
  canOperate = true,
  canReview = true,
  subject = "",
  development = false,
}: {
  inspect: (id: string) => void;
  canOperate?: boolean;
  canReview?: boolean;
  subject?: string;
  development?: boolean;
}) {
  const [data, setData] = useState<ReleaseData | null>(null),
    [busy, setBusy] = useState(""),
    [error, setError] = useState("");
  async function refresh() {
    setData(await request<ReleaseData>("/adapt"));
  }
  useEffect(() => {
    void refresh().catch((e) => setError(String(e)));
  }, []);
  async function action(
    path: string,
    body: unknown = {},
    label = "Applying change",
  ) {
    setBusy(label);
    setError("");
    try {
      await request("/adapt" + path, body);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy("");
    }
  }
  return (
    <>
      <section className="platform-intro">
        <div>
          <span className="pill neutral">ADAPT / RELEASE CONTROL</span>
          <h2>Evaluate. Review. Roll out. Recover.</h2>
          <p>
            Versioned configurations, reproducible gates, a 20% local canary
            router, and rollback on candidate failure. All traffic here uses the
            synthetic incident workflow.
          </p>
        </div>
        <div className="release-scope">
          <GitBranch size={24} />
          <strong>Local deployment lab</strong>
          <small>Explicit review · persistent history</small>
        </div>
      </section>
      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}
      {busy && (
        <div className="work-status" role="status">
          <LoaderCircle size={16} className="spin" />
          {busy}…
        </div>
      )}
      {data && (
        <>
          <section className="deployment-panel">
            <div className="panel-head">
              <h2>Deployment state</h2>
              <span className="micro">REVISION {data.state.revision}</span>
            </div>
            <div className="deployment-body">
              <div>
                <small>Stable configuration</small>
                <strong>{data.state.stable}</strong>
                <span>
                  {100 - data.state.candidate_percent}% of routed requests
                </span>
              </div>
              <GitBranch size={24} />
              <div>
                <small>Candidate configuration</small>
                <strong>{data.state.candidate || "No active canary"}</strong>
                <span>
                  {data.state.candidate
                    ? `${data.state.candidate_percent}% routing · ${data.candidate_samples}/${data.minimum_samples} required candidate probes`
                    : "Evaluate a different configuration to start"}
                </span>
              </div>
            </div>
            <div className="release-buttons">
              <button
                className="secondary"
                disabled={!!busy || !canOperate || !data.state.candidate}
                onClick={() =>
                  void action(
                    "/batch",
                    {},
                    "Running five candidate and five stable probes",
                  )
                }
              >
                <Play size={15} /> Run validation batch
              </button>
              <button
                className="secondary"
                disabled={!!busy || !canOperate || !data.state.candidate}
                onClick={() =>
                  void action(
                    "/batch",
                    { inject_outage: true },
                    "Injecting candidate availability failure",
                  )
                }
              >
                <CircleAlert size={15} /> Inject candidate outage
              </button>
              <button
                className="primary"
                disabled={
                  !!busy ||
                  !canReview ||
                  !data.state.candidate ||
                  data.candidate_samples < data.minimum_samples
                }
                onClick={() =>
                  void action("/promote", {}, "Promoting candidate")
                }
              >
                <Check size={15} /> Promote candidate
              </button>
              <button
                className="secondary"
                disabled={
                  !!busy ||
                  !canReview ||
                  (!data.state.candidate && !data.state.previous)
                }
                onClick={() => void action("/rollback", {}, "Rolling back")}
              >
                <RotateCcw size={15} /> Roll back
              </button>
            </div>
            <p className="deployment-note">
              Validation batches deliberately select five candidate and five
              stable requests. They verify both routes; their 50/50 composition
              does not estimate live traffic allocation.
            </p>
          </section>
          <div className="version-grid">
            {data.versions.map((v) => (
              <section className="version-card" key={v.id}>
                <div className="drift-card-head">
                  <h3>{v.id}</h3>
                  {v.id === data.state.stable && (
                    <span className="pill success">Stable</span>
                  )}
                </div>
                <dl>
                  <div>
                    <dt>Evidence selection</dt>
                    <dd>{v.source_filter}</dd>
                  </div>
                  <div>
                    <dt>Maximum fixture retries</dt>
                    <dd>{v.retry_budget}</dd>
                  </div>
                  <div>
                    <dt>Missing evidence</dt>
                    <dd>{v.fallback}</dd>
                  </div>
                </dl>
                <button
                  className="secondary"
                  disabled={!!busy || !canOperate}
                  onClick={() =>
                    void action(
                      "/proposals",
                      { version: v.id },
                      "Evaluating four fixture scenarios",
                    )
                  }
                >
                  <FlaskConical size={15} /> Evaluate {v.id}
                </button>
              </section>
            ))}
          </div>
          <section className="policy-events">
            <div className="panel-head">
              <h2>Evaluated proposals</h2>
              <span className="micro">CODE + CONFIGURATION DIGEST</span>
            </div>
            {data.proposals.length ? (
              data.proposals.map((p) => (
                <article className="proposal-row" key={p.id}>
                  <div className="policy-event-head">
                    <strong>{p.candidate}</strong>
                    <span
                      className={"pill " + (p.eligible ? "success" : "danger")}
                    >
                      {p.eligible ? "Gates passed" : "Gates failed"}
                    </span>
                    <span>
                      {p.rows.filter((r) => r.passed).length}/{p.rows.length}{" "}
                      cases
                    </span>
                    <code>{p.code_digest.slice(0, 10)}</code>
                  </div>
                  <div className="gate-list">
                    {p.gates.map((g) => (
                      <span
                        key={g.name}
                        className={g.passed ? "text-good" : "text-bad"}
                      >
                        {g.passed ? (
                          <Check size={14} />
                        ) : (
                          <CircleAlert size={14} />
                        )}{" "}
                        {g.name}
                      </span>
                    ))}
                  </div>
                  {p.eligible &&
                  p.status === "evaluated" &&
                  p.based_on_revision === data.state.revision &&
                  p.candidate !== data.state.stable &&
                  !data.state.candidate ? (
                    <button
                      className="primary"
                      disabled={
                        !!busy ||
                        !canReview ||
                        (!development &&
                          (!p.created_by || p.created_by === subject))
                      }
                      onClick={() =>
                        void action(
                          "/proposals/" + p.id + "/approve",
                          {},
                          "Starting approved canary",
                        )
                      }
                    >
                      <ShieldCheck size={15} /> Approve 20% canary
                    </button>
                  ) : (
                    <p className="proposal-state">
                      {!p.eligible
                        ? "Promotion blocked by evaluation."
                        : p.status === "canary"
                          ? "This evaluation has already been used."
                          : p.candidate === data.state.stable
                            ? "This configuration is already stable."
                            : "Deployment revision changed; evaluate again."}
                    </p>
                  )}
                </article>
              ))
            ) : (
              <div className="empty">
                <FlaskConical size={28} />
                <strong>No evaluated proposals</strong>
                <p>
                  Evaluate a version to record its assertions and release gates.
                </p>
              </div>
            )}
          </section>
          {data.runs.length > 0 && (
            <section className="policy-events release-results">
              <div className="panel-head">
                <h2>Recent routed executions</h2>
                <span className="micro">ACTUAL LAB RUNS</span>
              </div>
              {data.runs.slice(0, 10).map((r) => (
                <article className="replay-row" key={r.id}>
                  <span className={"pill " + (r.passed ? "success" : "danger")}>
                    {r.passed ? "Passed" : "Failed"}
                  </span>
                  <div>
                    <strong>
                      {r.version} · {r.route}
                    </strong>
                    <small>
                      {r.injected_outage
                        ? "Injected availability failure"
                        : r.scenario.replaceAll("_", " ")}
                    </small>
                  </div>
                  <button
                    className="secondary"
                    onClick={() => inspect(r.trace_id)}
                  >
                    Trace <ArrowUpRight size={14} />
                  </button>
                </article>
              ))}
            </section>
          )}
          <section className="release-history">
            <h2>Release history</h2>
            {data.events.length ? (
              data.events.slice(0, 12).map((e) => (
                <article key={e.id}>
                  <span className="history-dot" />
                  <div>
                    <strong>{e.kind.replaceAll("_", " ")}</strong>
                    <p>
                      {e.reason ||
                        e.stable ||
                        e.candidate ||
                        "Evaluation recorded"}
                      {e.eligible === false ? " · gates failed" : ""}
                    </p>
                  </div>
                  <time>
                    {new Date(e.created_at * 1000).toLocaleTimeString()}
                  </time>
                </article>
              ))
            ) : (
              <p>Deployment actions will appear here.</p>
            )}
          </section>
        </>
      )}
      <div className="method-note">
        <strong>Release boundary</strong>
        <p>
          The router changes only this lab’s fixture workload. A failing
          candidate run removes the candidate from routing. Required-auth mode
          verifies reviewer permissions and separates proposer from approver.
          Production still needs enterprise SSO, held-out datasets, durable
          workflows, real traffic, SLOs, and deployment integrations.
        </p>
      </div>
    </>
  );
}
