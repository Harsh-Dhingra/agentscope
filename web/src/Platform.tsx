import { useEffect, useState } from "react";
import {
  Activity,
  ArrowRight,
  Check,
  LoaderCircle,
  ShieldCheck,
  LockKeyhole,
} from "lucide-react";

import { request } from "./http";
type Metric = {
  name: string;
  kind: string;
  unit: string;
  n_reference: number;
  n_current: number;
  reference_mean: number;
  current_mean: number;
  ks_distance: number;
  p_value: number;
  adjusted_p_value: number;
  shift_detected: boolean;
  histogram: { edges: number[]; reference: number[]; current: number[] };
};
type Report = {
  id: string;
  label: string;
  source: string;
  method: string;
  alpha: number;
  min_effect: number;
  rows: Metric[];
  alert_count: number;
  limitations: string;
};
type PolicyEvent = {
  id: string;
  created_at: number;
  principal: string;
  role: string;
  action: { tool: string; target: string; idempotency_key: string };
  decision: string;
  reason: string;
  created_by?: string;
  approved_by?: string;
  executed: boolean;
  replayed?: boolean;
  result: Record<string, unknown> | null;
};
const scenarios = {
  stable: "Stationary control",
  latency_spike: "Latency spike",
  quality_regression: "Quality regression",
  knowledge_aging: "Knowledge aging",
};
function format(n: number) {
  return n === 0 ? "0" : Math.abs(n) >= 10 ? n.toFixed(1) : n.toFixed(3);
}

export function DriftPanel({ canOperate = true }: { canOperate?: boolean }) {
  const [reports, setReports] = useState<Report[]>([]),
    [selected, setSelected] = useState<string | null>(null),
    [scenario, setScenario] = useState("latency_spike"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function refresh() {
    const all = await request<Report[]>("/drift/reports");
    setReports(all);
    setSelected((s) => s || all[0]?.id || null);
  }
  useEffect(() => {
    void refresh().catch((e) => setError(String(e)));
  }, []);
  async function run() {
    setBusy(true);
    setError("");
    try {
      const report = await request<Report>("/drift/demo", { scenario });
      await refresh();
      setSelected(report.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  const report = reports.find((r) => r.id === selected);
  return (
    <>
      <section className="platform-intro">
        <div>
          <span className="pill neutral">PERFORMANCE / DRIFT</span>
          <h2>Detect a shift. Keep the evidence.</h2>
          <p>
            Five numeric monitoring categories, reference/current windows,
            effect sizes, and corrected statistical tests. The built-in
            scenarios use seeded synthetic data.
          </p>
        </div>
        <div className="platform-actions">
          <label>
            Window scenario
            <select
              value={scenario}
              onChange={(e) => setScenario(e.target.value)}
            >
              {Object.entries(scenarios).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <button
            className="primary"
            disabled={busy || !canOperate}
            onClick={() => void run()}
          >
            {busy ? (
              <LoaderCircle className="spin" size={16} />
            ) : (
              <Activity size={16} />
            )}{" "}
            {busy ? "Analyzing…" : "Compare windows"}
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
          <div className="report-toolbar">
            <label>
              Recorded analysis
              <select
                value={selected || ""}
                onChange={(e) => setSelected(e.target.value)}
              >
                {reports.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.label} · {r.id.slice(0, 8)}
                  </option>
                ))}
              </select>
            </label>
            <span
              className={"pill " + (report.alert_count ? "warning" : "success")}
            >
              {report.alert_count} shifts detected
            </span>
            <span>{report.source}</span>
          </div>
          <div className="drift-grid">
            {report.rows.map((metric) => (
              <section className="drift-card" key={metric.name}>
                <div className="drift-card-head">
                  <div>
                    <div className="eyebrow">{metric.kind.toUpperCase()}</div>
                    <h3>{metric.name}</h3>
                  </div>
                  <span
                    className={
                      "pill " + (metric.shift_detected ? "warning" : "success")
                    }
                  >
                    {metric.shift_detected
                      ? "Shift detected"
                      : "No shift detected"}
                  </span>
                </div>
                <div className="mean-row">
                  <div>
                    <small>Reference mean</small>
                    <strong>
                      {format(metric.reference_mean)} <em>{metric.unit}</em>
                    </strong>
                  </div>
                  <ArrowRight size={16} />
                  <div>
                    <small>Current mean</small>
                    <strong>
                      {format(metric.current_mean)} <em>{metric.unit}</em>
                    </strong>
                  </div>
                </div>
                <Distribution metric={metric} />
                <div className="distribution-legend">
                  <span>
                    <i className="legend-reference" />
                    Reference · n={metric.n_reference}
                  </span>
                  <span>
                    <i className="legend-current" />
                    Current · n={metric.n_current}
                  </span>
                </div>
                <dl className="stat-row">
                  <div>
                    <dt>KS distance</dt>
                    <dd>{metric.ks_distance.toFixed(3)}</dd>
                  </div>
                  <div>
                    <dt>Adjusted p</dt>
                    <dd>{metric.adjusted_p_value.toFixed(4)}</dd>
                  </div>
                  <div>
                    <dt>Review</dt>
                    <dd>{metric.shift_detected ? "Required" : "Monitor"}</dd>
                  </div>
                </dl>
              </section>
            ))}
          </div>
          <div className="method-note">
            <strong>Method & interpretation</strong>
            <p>
              {report.method}. Alert requires adjusted p &lt; {report.alpha} and
              KS distance ≥ {report.min_effect}.
            </p>
            <p>{report.limitations}</p>
            <p>
              Custom windows can be submitted through{" "}
              <code>POST /api/drift/analyze</code>. Raw numeric samples are
              analyzed in memory; reports store summary statistics and
              histograms.
            </p>
          </div>
        </>
      ) : (
        <div className="empty">
          <Activity size={30} />
          <strong>No window comparisons yet</strong>
          <p>
            Run a stationary control, then inject a shift and compare the
            results.
          </p>
        </div>
      )}
    </>
  );
}
function Distribution({ metric }: { metric: Metric }) {
  const h = metric.histogram,
    max = Math.max(...h.reference, ...h.current, 0.01);
  return (
    <svg
      className="distribution"
      viewBox="0 0 340 110"
      role="img"
      aria-label={`${metric.name}: reference and current distributions. KS distance ${metric.ks_distance.toFixed(3)}.`}
    >
      <line x1="16" y1="86" x2="324" y2="86" stroke="#dbe4e8" />
      {h.reference.map((v, i) => (
        <g key={i}>
          <rect
            x={18 + i * 25.3}
            y={86 - (v / max) * 66}
            width="10"
            height={(v / max) * 66}
            fill="#b6cad7"
          >
            <title>
              Reference bin {i + 1}: {(v * 100).toFixed(1)}%
            </title>
          </rect>
          <rect
            x={29 + i * 25.3}
            y={86 - (h.current[i] / max) * 66}
            width="10"
            height={(h.current[i] / max) * 66}
            fill="#45927d"
          >
            <title>
              Current bin {i + 1}: {(h.current[i] * 100).toFixed(1)}%
            </title>
          </rect>
        </g>
      ))}
      <text x="16" y="104" fill="#8196a5" fontSize="10">
        {format(h.edges[0])}
      </text>
      <text x="324" y="104" fill="#8196a5" fontSize="10" textAnchor="end">
        {format(h.edges[h.edges.length - 1])} {metric.unit}
      </text>
      <text x="16" y="11" fill="#8196a5" fontSize="9">
        Relative frequency · peak {(max * 100).toFixed(0)}%
      </text>
    </svg>
  );
}

export function GuardianPanel({
  canOperate = true,
  canReview = true,
  subject = "",
  development = false,
}: {
  canOperate?: boolean;
  canReview?: boolean;
  subject?: string;
  development?: boolean;
}) {
  const [events, setEvents] = useState<PolicyEvent[]>([]),
    [scenario, setScenario] = useState("unauthorized_write"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function refresh() {
    setEvents(await request<PolicyEvent[]>("/guardian/events"));
  }
  useEffect(() => {
    void refresh().catch((e) => setError(String(e)));
  }, []);
  async function run() {
    setBusy(true);
    setError("");
    try {
      await request("/guardian/demo", { scenario });
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function approve(id: string) {
    setBusy(true);
    setError("");
    try {
      await request("/guardian/events/" + id + "/approve", {});
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <section className="platform-intro">
        <div>
          <span className="pill neutral">GUARDIAN / TOOL POLICY</span>
          <h2>Decide before the tool executes.</h2>
          <p>
            A deterministic gateway checks the principal, resource scope, and
            approval requirement. Demonstrations use server-defined synthetic
            identities and tools.
          </p>
        </div>
        <div className="platform-actions">
          <label>
            Policy scenario
            <select
              value={scenario}
              onChange={(e) => setScenario(e.target.value)}
            >
              <option value="unauthorized_write">Unauthorized restart</option>
              <option value="approval_required">Restart needs approval</option>
              <option value="allowed_read">Permitted health check</option>
              <option value="blocked_export">Blocked log export</option>
            </select>
          </label>
          <button
            className="primary"
            disabled={busy || !canOperate}
            onClick={() => void run()}
          >
            {busy ? (
              <LoaderCircle className="spin" size={16} />
            ) : (
              <ShieldCheck size={16} />
            )}{" "}
            Submit request
          </button>
        </div>
      </section>
      <div className="policy-flow">
        <span>
          <LockKeyhole size={17} /> Principal & scope
        </span>
        <ArrowRight size={15} />
        <span>
          <ShieldCheck size={17} /> Deterministic policy
        </span>
        <ArrowRight size={15} />
        <span>
          <Check size={17} /> Approval + idempotency
        </span>
      </div>
      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}
      <section className="policy-events">
        <div className="panel-head">
          <h2>Decision ledger</h2>
          <span className="micro">SYNTHETIC TOOL EXECUTION</span>
        </div>
        {events.length ? (
          events.map((event) => (
            <article className="policy-event" key={event.id}>
              <div className="policy-event-head">
                <span
                  className={
                    "pill " +
                    (event.decision === "denied"
                      ? "danger"
                      : event.decision === "approval_required"
                        ? "warning"
                        : "success")
                  }
                >
                  {event.decision.replaceAll("_", " ")}
                </span>
                <strong>{event.action.tool}</strong>
                <span>{event.action.target}</span>
                <code>{event.id.slice(0, 8)}</code>
              </div>
              <p>{event.reason}</p>
              <div className="policy-facts">
                {event.created_by && (
                  <span>
                    Requested by <strong>{event.created_by}</strong>
                  </span>
                )}
                {event.approved_by && (
                  <span>
                    Approved by <strong>{event.approved_by}</strong>
                  </span>
                )}
                <span>
                  Tool principal <strong>{event.principal}</strong>
                </span>
                <span>
                  Role <strong>{event.role}</strong>
                </span>
                <span>
                  Executed{" "}
                  <strong className={event.executed ? "text-good" : ""}>
                    {event.executed ? "Yes" : "No"}
                  </strong>
                </span>
              </div>
              {event.result && (
                <pre>{JSON.stringify(event.result, null, 2)}</pre>
              )}
              {event.decision === "approval_required" && (
                <button
                  className="primary"
                  disabled={
                    busy ||
                    !canReview ||
                    (!development &&
                      (!event.created_by || event.created_by === subject))
                  }
                  onClick={() => void approve(event.id)}
                >
                  Approve demo restart
                </button>
              )}
            </article>
          ))
        ) : (
          <div className="empty">
            <ShieldCheck size={30} />
            <strong>No policy decisions yet</strong>
            <p>
              Submit a request to see whether execution is allowed, denied, or
              held for review.
            </p>
          </div>
        )}
      </section>
      <div className="method-note">
        <strong>Enforcement boundary</strong>
        <p>
          Denied actions never enter the executor. Approved restarts change only
          the synthetic worker’s stored restart counter. Idempotency keys and a
          transaction protect against duplicate effects.
        </p>
        <p>
          Required-auth mode checks reviewer permissions and requires a
          different principal from the requester. Local credentials are not
          enterprise SSO. Tools still operate only on synthetic resources.
        </p>
      </div>
    </>
  );
}
