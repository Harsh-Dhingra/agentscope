import { useEffect, useState } from "react";
import { request } from "./http";
import { Distribution, FixtureDriftPanel, type Metric } from "./Platform";

type Evidence = { trace_id: string; value: number };
type Row = Partial<Metric> & {
  name: string;
  key: string;
  status: string;
  n_reference: number;
  n_current: number;
  missing_reference: number;
  missing_current: number;
  reference_evidence: Evidence[];
  current_evidence: Evidence[];
};
type Report = {
  id: string;
  source: string;
  created_at: number;
  rows: Row[];
  alert_count: number;
  limitations: string;
  windows: {
    service: string;
    reference_start: number;
    reference_end: number;
    current_start: number;
    current_end: number;
  };
  coverage: Record<
    string,
    {
      root_candidates: number;
      eligible_traces: number;
      excluded_trace_ids: string[];
    }
  >;
};
const end = Math.floor(Date.now() / 3600000) * 3600000;
const utc = (ms: number) => new Date(ms).toISOString().slice(0, 16);

export function DriftPanel({
  canOperate,
  inspect,
}: {
  canOperate: boolean;
  inspect: (id: string) => void;
}) {
  const [mode, setMode] = useState("traces");
  return (
    <>
      <div className="report-toolbar">
        <button
          className={mode === "traces" ? "primary" : "secondary"}
          onClick={() => setMode("traces")}
        >
          Collected traces
        </button>
        <button
          className={mode === "fixtures" ? "primary" : "secondary"}
          onClick={() => setMode("fixtures")}
        >
          Synthetic windows
        </button>
      </div>
      {mode === "traces" ? (
        <Collected canOperate={canOperate} inspect={inspect} />
      ) : (
        <FixtureDriftPanel canOperate={canOperate} />
      )}
    </>
  );
}
function Collected({
  canOperate,
  inspect,
}: {
  canOperate: boolean;
  inspect: (id: string) => void;
}) {
  const [service, setService] = useState("incident-agent"),
    [rs, setRs] = useState(utc(end - 7200000)),
    [re, setRe] = useState(utc(end - 3600000)),
    [cs, setCs] = useState(utc(end - 3600000)),
    [ce, setCe] = useState(utc(end));
  const [reports, setReports] = useState<Report[]>([]),
    [selected, setSelected] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const refresh = async () => {
    const data = (await request<Report[]>("/drift/reports")).filter(
      (r) => r.source === "collected_traces",
    );
    setReports(data);
    setSelected((old) => old || data[0]?.id || "");
  };
  useEffect(() => {
    void refresh().catch((e) => setError(String(e)));
  }, []);
  async function run() {
    setBusy(true);
    setError("");
    try {
      const r = await request<Report>("/drift/traces", {
        service,
        reference_start: Date.parse(rs + "Z") / 1000,
        reference_end: Date.parse(re + "Z") / 1000,
        current_start: Date.parse(cs + "Z") / 1000,
        current_end: Date.parse(ce + "Z") / 1000,
      });
      await refresh();
      setSelected(r.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  const report = reports.find((r) => r.id === selected);
  useEffect(() => {
    if (report) {
      setService(report.windows.service);
      setRs(utc(report.windows.reference_start * 1000));
      setRe(utc(report.windows.reference_end * 1000));
      setCs(utc(report.windows.current_start * 1000));
      setCe(utc(report.windows.current_end * 1000));
    }
  }, [selected, reports]);
  return (
    <>
      <section className="platform-intro">
        <div>
          <span className="pill neutral">COLLECTED TRACE EVIDENCE</span>
          <h2>Compare behavior across time.</h2>
          <p>
            Choose a root service and two nonoverlapping UTC windows. Each
            observation comes from a stored trace. At least 30 usable traces per
            metric and window are required.
          </p>
        </div>
      </section>
      <div className="trace-window-form">
        <label>
          Root service
          <input value={service} onChange={(e) => setService(e.target.value)} />
        </label>
        {(
          [
            ["Reference start (UTC)", rs, setRs],
            ["Reference end (UTC)", re, setRe],
            ["Current start (UTC)", cs, setCs],
            ["Current end (UTC)", ce, setCe],
          ] as const
        ).map(([label, value, setter]) => (
          <label key={label}>
            {label}
            <input
              type="datetime-local"
              value={value}
              onChange={(e) => setter(e.target.value)}
            />
          </label>
        ))}
        <button
          className="primary"
          disabled={
            busy || !canOperate || !service || ![rs, re, cs, ce].every(Boolean)
          }
          onClick={() => void run()}
        >
          {busy ? "Analyzing traces…" : "Analyze collected traces"}
        </button>
      </div>
      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}
      {report ? (
        <>
          <div className="report-toolbar">
            <label>
              Collected comparison
              <select
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
              >
                {reports.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.windows.service} ·{" "}
                    {new Date(r.created_at * 1000).toLocaleString()}
                  </option>
                ))}
              </select>
            </label>
            <span className="pill neutral">
              {report.alert_count} distribution shifts ·{" "}
              {report.rows.filter((r) => r.status === "insufficient").length}{" "}
              insufficient metrics
            </span>
          </div>
          <div className="method-note">
            <strong>{report.windows.service} · saved evidence snapshot</strong>
            <p>
              Reference:{" "}
              {new Date(report.windows.reference_start * 1000).toISOString()} →{" "}
              {new Date(report.windows.reference_end * 1000).toISOString()}
              <br />
              Current:{" "}
              {new Date(
                report.windows.current_start * 1000,
              ).toISOString()} →{" "}
              {new Date(report.windows.current_end * 1000).toISOString()}
            </p>
            {Object.entries(report.coverage).map(([name, c]) => (
              <p key={name}>
                {name}: {c.eligible_traces} eligible traces /{" "}
                {c.root_candidates} root spans. {c.excluded_trace_ids.length}{" "}
                traces excluded for parent/root coverage or end-time checks.
              </p>
            ))}
          </div>
          <div className="drift-grid">
            {report.rows.map((row) => (
              <section className="drift-card" key={row.key}>
                <div className="drift-card-head">
                  <h3>{row.name}</h3>
                  <span
                    className={
                      "pill " +
                      (row.status === "insufficient"
                        ? "neutral"
                        : row.shift_detected
                          ? "warning"
                          : "success")
                    }
                  >
                    {row.status === "insufficient"
                      ? "Not enough evidence"
                      : row.shift_detected
                        ? "Distribution shift"
                        : "No shift detected"}
                  </span>
                </div>
                <p>
                  Reference n={row.n_reference} · Current n={row.n_current}
                </p>
                <p>
                  Missing or invalid telemetry: {row.missing_reference}{" "}
                  reference · {row.missing_current} current
                </p>
                {row.status === "tested" ? (
                  <>
                    <div className="mean-row">
                      <div>
                        <small>Reference mean</small>
                        <strong>
                          {row.reference_mean?.toFixed(2)} {row.unit}
                        </strong>
                      </div>
                      <div>
                        <small>Current mean</small>
                        <strong>
                          {row.current_mean?.toFixed(2)} {row.unit}
                        </strong>
                      </div>
                    </div>
                    <Distribution metric={row as Metric} />
                    <p>Reference: gray · Current: green</p>
                    <p>
                      KS distance {row.ks_distance?.toFixed(3)} · Adjusted p{" "}
                      {row.adjusted_p_value?.toFixed(4)}
                    </p>
                  </>
                ) : (
                  <p>
                    Collect at least 30 valid observations in each window.
                    Missing measurements are never filled with zero.
                  </p>
                )}
                <details className="trace-evidence">
                  <summary>Inspect source traces</summary>
                  {(["reference", "current"] as const).map((group) => (
                    <div key={group}>
                      <h4>{group}</h4>
                      {row[`${group}_evidence`].map((e) => (
                        <button
                          key={e.trace_id}
                          onClick={() => inspect(e.trace_id)}
                          aria-label={`Inspect ${group} trace ${e.trace_id}`}
                        >
                          <code>{e.trace_id.slice(0, 12)}</code>
                          <span>
                            {e.value.toFixed(2)} {row.unit}
                          </span>
                        </button>
                      ))}
                    </div>
                  ))}
                </details>
              </section>
            ))}
          </div>
          <div className="method-note">
            <strong>Distribution change is not a quality verdict</strong>
            <p>
              KS distance with 399 permutations; Bonferroni correction across
              tested metrics. A shift requires adjusted p &lt; 0.05 and distance
              ≥ 0.2. No quality labels or model-accuracy conclusions are
              inferred.
            </p>
            <p>{report.limitations}</p>
            <p>
              Windows include root start times and exclude end boundaries;
              maximum 256 root spans per window. Narrow the range if it exceeds
              this limit. Tool server spans are excluded to avoid counting both
              sides of an MCP call. Retry counts require explicit attempt
              metadata.
            </p>
          </div>
        </>
      ) : (
        <div className="empty">
          <strong>No collected-trace comparison yet</strong>
          <p>
            Analyze existing telemetry, or use the documented synthetic trace
            fixture to exercise this workflow.
          </p>
        </div>
      )}
    </>
  );
}
