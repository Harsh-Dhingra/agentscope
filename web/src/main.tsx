import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  TrendingUp,
  Users,
  GitBranch,
  Workflow,
  FlaskConical,
  Plug,
  Play,
  ArrowUpRight,
  ChevronRight,
  ShieldCheck,
  CircleAlert,
  Check,
  Search,
  Radio,
  LoaderCircle,
  Terminal,
  Clock3,
  Layers,
  X,
} from "lucide-react";
import { ReviewPanel, AdaptPanel } from "./Control";
import { DriftPanel, GuardianPanel } from "./Platform";
import "./style.css";

type Summary = {
  trace_id: string;
  name: string;
  started_ns: number;
  duration_ms: number;
  span_count: number;
  error_count: number;
  finding_count: number;
  evaluation_failed: boolean;
  runtime: string;
  scenario: string;
  variant: string;
  outcome: string;
  service: string;
  tokens: number;
  has_usage: boolean;
};
type Span = {
  trace_id: string;
  span_id: string;
  parent_id: string | null;
  name: string;
  start_ns: number;
  end_ns: number;
  status: string;
  attributes: Record<string, unknown>;
  resource: Record<string, unknown>;
  events: unknown[];
  links: unknown[];
};
type Run = {
  id: string;
  trace_id: string;
  scenario: string;
  variant: string;
  runtime: string;
  answer: string;
  outcome: string;
  passed: boolean;
  assertions: { name: string; passed: boolean }[];
  duration_ms: number;
};
type Detail = {
  summary: Summary;
  spans: Span[];
  findings: {
    severity: string;
    title: string;
    detail: string;
    span_id: string;
  }[];
  run: Run | null;
};
type Experiment = {
  id: string;
  dataset: string;
  runtime: string;
  rows: Run[];
  summary: Record<string, { passed: number; total: number }>;
  limitations: string;
};
const labels: Record<string, string> = {
  healthy: "Grounded response",
  stale_evidence: "Stale evidence",
  tool_timeout: "Tool timeout",
  retry_loop: "Retry storm",
};
const pages: Record<
  string,
  { label: string; title: string; description: string }
> = {
  traces: {
    label: "Trace explorer",
    title: "Follow every execution.",
    description:
      "Trace model calls, delegated work, and tool failures in one place.",
  },
  experiments: {
    label: "Experiments",
    title: "Turn failures into evidence.",
    description:
      "Compare implementations against the same versioned fault scenarios.",
  },
  drift: {
    label: "Performance & drift",
    title: "Know when behavior changes.",
    description:
      "Compare reference and current distributions with explicit statistical assumptions.",
  },
  guardian: {
    label: "Guardian",
    title: "Put policy before execution.",
    description:
      "Inspect decisions, review pending actions, and verify bounded tool effects.",
  },
  review: {
    label: "Review & replay",
    title: "Make the evidence inspectable.",
    description:
      "Bounded analysis, explicit uncertainty, and reproducible regression cases.",
  },
  adapt: {
    label: "Adapt & release",
    title: "Ship changes with a recovery path.",
    description:
      "Move a tested configuration through review, canary validation, and controlled promotion.",
  },
  connect: {
    label: "Connect an agent",
    title: "Instrument once. See the path.",
    description:
      "Send OpenTelemetry spans from your Python application to a local collector.",
  },
};
const pretty = (s: string) => labels[s] || s.replaceAll("_", " ");
async function api<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(
    "/api" + path,
    body !== undefined
      ? {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      : undefined,
  );
  if (!r.ok) {
    let error;
    try {
      error = await r.json();
    } catch {
      error = { detail: r.statusText };
    }
    throw new Error(
      typeof error.detail === "string" ? error.detail : "Invalid request",
    );
  }
  return r.json();
}
function App() {
  const [page, setPage] = useState("traces"),
    [traces, setTraces] = useState<Summary[]>([]),
    [selected, setSelected] = useState<string | null>(null),
    [detail, setDetail] = useState<Detail | null>(null),
    [spanId, setSpanId] = useState<string | null>(null),
    [experiments, setExperiments] = useState<Experiment[]>([]),
    [filter, setFilter] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [connected, setConnected] = useState(false),
    [scenario, setScenario] = useState("stale_evidence"),
    [variant, setVariant] = useState("baseline"),
    [runtime, setRuntime] = useState("scripted"),
    [transport, setTransport] = useState("inprocess"),
    [tab, setTab] = useState("trace");
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [page]);
  async function refresh() {
    try {
      const [t, e] = await Promise.all([
        api<Summary[]>("/traces"),
        api<Experiment[]>("/experiments"),
      ]);
      setTraces(t);
      setExperiments(e);
      setConnected(true);
      setSelected((old) => old || t[0]?.trace_id || null);
    } catch (e) {
      setConnected(false);
      setError(String(e));
    }
  }
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 5000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    let live = true;
    if (!selected) {
      setDetail(null);
      return;
    }
    api<Detail>("/traces/" + selected)
      .then((d) => {
        if (live) {
          setDetail(d);
          setSpanId((old) =>
            d.spans.some((s) => s.span_id === old) ? old : d.spans[0]?.span_id,
          );
        }
      })
      .catch((e) => setError(String(e)));
    return () => {
      live = false;
    };
  }, [selected, traces]);
  async function run() {
    setBusy(true);
    setError("");
    try {
      const result = await api<Run>("/runs", {
        scenario,
        variant,
        runtime,
        transport,
      });
      await refresh();
      setSelected(result.trace_id);
      setPage("traces");
      setTab("trace");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function evaluate() {
    setBusy(true);
    setError("");
    try {
      await api("/experiments", {});
      await refresh();
      setPage("experiments");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  const visible = traces.filter((t) =>
    `${t.name} ${t.scenario} ${t.service} ${t.trace_id} ${t.runtime} ${t.variant}`
      .toLowerCase()
      .includes(filter.toLowerCase()),
  );
  const currentSpan = detail?.spans.find((s) => s.span_id === spanId);
  const median = traces.length
    ? [...traces].sort((a, b) => a.duration_ms - b.duration_ms)[
        Math.floor(traces.length / 2)
      ].duration_ms
    : 0;
  const active = detail?.summary;
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setPage("traces");
          }}
        >
          <span className="brand-icon">
            <Activity size={21} />
          </span>
          AgentScope<span className="version">LAB</span>
        </a>
        <div className="workspace">
          <span className="workspace-icon">H</span>
          <div>
            Harsh’s workspace<small>Local development</small>
          </div>
        </div>
        <div className="nav-label">OBSERVABILITY</div>
        <nav>
          {[
            ["traces", "Trace explorer", Workflow],
            ["experiments", "Experiments", FlaskConical],
            ["drift", "Performance & drift", TrendingUp],
            ["guardian", "Guardian", ShieldCheck],
            ["review", "Review & replay", Users],
            ["adapt", "Adapt & release", GitBranch],
            ["connect", "Connect an agent", Plug],
          ].map(([key, label, Icon]) => (
            <button
              key={String(key)}
              aria-label={String(label)}
              className={page === key ? "nav-item active" : "nav-item"}
              onClick={() => setPage(String(key))}
            >
              <Icon size={17} />
              <span>{String(label)}</span>
              {page === key && <ChevronRight size={14} />}
            </button>
          ))}
        </nav>
        <div className="side-note">
          <ShieldCheck size={19} />
          <strong>Content capture is off</strong>
          <p>
            Only allowlisted metadata is stored. Prompts and completions are
            excluded from traces.
          </p>
        </div>
        <div className="sidebar-bottom">
          <span className={connected ? "status-dot" : "status-dot off"} />
          {connected ? "Collector connected" : "Collector unavailable"}
          <span className="build">v0.3</span>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <span>
            Workspace <ChevronRight size={13} />{" "}
            <strong>{pages[page].label}</strong>
          </span>
          <div className="top-info">
            <span className="pill neutral">LOCAL</span>
            <a
              href="https://github.com/Harsh-Dhingra/agentscope"
              target="_blank"
              rel="noreferrer"
            >
              Source <ArrowUpRight size={14} />
            </a>
          </div>
        </header>
        <nav className="mobile-nav" aria-label="Mobile navigation">
          {Object.entries(pages).map(([key, value]) => (
            <button
              key={key}
              className={page === key ? "active" : ""}
              onClick={() => setPage(key)}
            >
              {value.label}
            </button>
          ))}
        </nav>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">AGENT RELIABILITY LAB</div>
              <h1>{pages[page].title}</h1>
              <p>{pages[page].description}</p>
            </div>
            <div className="live-label">
              <Radio size={14} />{" "}
              {connected
                ? page === "traces"
                  ? "Refreshing every 5s"
                  : "Collector online"
                : "Waiting for collector"}
            </div>
          </div>
          {error && (
            <div className="error-banner" role="alert">
              <CircleAlert size={16} />
              {error}
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={15} />
              </button>
            </div>
          )}
          {page === "review" && (
            <ReviewPanel
              inspect={(id) => {
                setSelected(id);
                setPage("traces");
                setTab("trace");
              }}
            />
          )}
          {page === "adapt" && (
            <AdaptPanel
              inspect={(id) => {
                setSelected(id);
                setPage("traces");
                setTab("trace");
              }}
            />
          )}
          {page === "drift" && <DriftPanel />}
          {page === "guardian" && <GuardianPanel />}
          {page === "traces" && (
            <>
              <section className="metrics" aria-label="Observed trace metrics">
                <Metric
                  icon={<Layers size={17} />}
                  title="Collected traces"
                  value={String(traces.length)}
                  sub="Most recent 200 traces"
                />
                <Metric
                  icon={<CircleAlert size={17} />}
                  title="With execution errors"
                  value={String(traces.filter((t) => t.error_count > 0).length)}
                  sub="A recovered error still appears"
                />
                <Metric
                  icon={<Clock3 size={17} />}
                  title="Median trace duration"
                  value={traces.length ? `${median.toFixed(0)} ms` : "—"}
                  sub="Mixed workload sample"
                />
                <Metric
                  icon={<ShieldCheck size={17} />}
                  title="Evaluation failures"
                  value={String(
                    traces.filter((t) => t.evaluation_failed).length,
                  )}
                  sub="Explicit workload assertions failed"
                />
              </section>
              <section className="run-panel">
                <div className="run-title">
                  <span className="small-icon">
                    <Play size={15} />
                  </span>
                  <div>
                    <strong>Run a demo workload</strong>
                    <small>
                      LangGraph incident analyst · synthetic runbook
                    </small>
                  </div>
                </div>
                <div className="run-controls">
                  <label>
                    Scenario
                    <select
                      value={scenario}
                      onChange={(e) => setScenario(e.target.value)}
                    >
                      {Object.entries(labels).map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Implementation
                    <select
                      value={variant}
                      onChange={(e) => setVariant(e.target.value)}
                    >
                      <option value="baseline">Baseline</option>
                      <option value="guarded">With controls</option>
                    </select>
                  </label>
                  <label>
                    Inference
                    <select
                      value={runtime}
                      onChange={(e) => setRuntime(e.target.value)}
                    >
                      <option value="scripted">Scripted fixture</option>
                      <option value="ollama">Local Ollama</option>
                    </select>
                  </label>
                  <label>
                    Tool transport
                    <select
                      value={transport}
                      onChange={(e) => setTransport(e.target.value)}
                    >
                      <option value="inprocess">In process</option>
                      <option value="mcp">MCP · subprocess</option>
                    </select>
                  </label>
                  <button
                    className="primary"
                    onClick={() => void run()}
                    disabled={busy}
                  >
                    {busy ? (
                      <LoaderCircle className="spin" size={15} />
                    ) : (
                      <Play size={15} />
                    )}{" "}
                    {busy ? "Running…" : "Run scenario"}
                  </button>
                </div>
              </section>
              <div className="explorer-grid">
                <section className="trace-list">
                  <div className="panel-head">
                    <h2>
                      Recent traces <span>{visible.length}</span>
                    </h2>
                    <span className="micro">NEWEST FIRST</span>
                  </div>
                  <div className="search">
                    <Search size={15} />
                    <input
                      aria-label="Filter traces"
                      placeholder="Search scenario, service, or trace ID"
                      value={filter}
                      onChange={(e) => setFilter(e.target.value)}
                    />
                  </div>
                  <div className="trace-items">
                    {visible.length === 0 ? (
                      <div className="empty">
                        <Workflow size={26} />
                        <strong>
                          {filter
                            ? "No matching traces"
                            : "Your first trace starts here"}
                        </strong>
                        <p>
                          {filter
                            ? "Try another scenario or trace ID."
                            : "Run a demo workload or connect your own agent."}
                        </p>
                      </div>
                    ) : (
                      visible.map((t) => (
                        <button
                          className={
                            "trace-item " +
                            (t.trace_id === selected ? "selected" : "")
                          }
                          key={t.trace_id}
                          onClick={() => {
                            setSelected(t.trace_id);
                            setTab("trace");
                          }}
                        >
                          <div className="trace-item-top">
                            <span
                              className={
                                "trace-status " +
                                (t.error_count
                                  ? "bad"
                                  : t.finding_count
                                    ? "warn"
                                    : "good")
                              }
                            >
                              {t.error_count ? (
                                <CircleAlert size={15} />
                              ) : t.finding_count ? (
                                <CircleAlert size={15} />
                              ) : (
                                <Check size={15} />
                              )}
                            </span>
                            <strong>{pretty(t.scenario)}</strong>
                            <span className="duration">
                              {t.duration_ms.toFixed(0)} ms
                            </span>
                          </div>
                          <div className="trace-item-mid">
                            <span>
                              {t.variant === "guarded"
                                ? "With controls"
                                : pretty(t.variant)}
                            </span>
                            <span>·</span>
                            <span>
                              {t.runtime === "scripted"
                                ? "Fixture"
                                : t.runtime === "ollama"
                                  ? "Ollama"
                                  : t.service}
                            </span>
                            <span>·</span>
                            <span>{t.span_count} spans</span>
                          </div>
                          <div className="trace-item-bottom">
                            <code>{t.trace_id.slice(0, 12)}</code>
                            <span className={"outcome " + t.outcome}>
                              {pretty(t.outcome)}
                            </span>
                          </div>
                        </button>
                      ))
                    )}
                  </div>
                </section>
                <section className="inspector">
                  {detail && active ? (
                    <>
                      <div className="inspector-heading">
                        <div>
                          <div className="eyebrow">TRACE DETAILS</div>
                          <h2>{pretty(active.scenario)}</h2>
                          <code>{active.trace_id}</code>
                        </div>
                        <span
                          className={
                            "pill " +
                            (active.error_count
                              ? "danger"
                              : active.finding_count
                                ? "warning"
                                : "success")
                          }
                        >
                          {active.error_count
                            ? `${active.error_count} execution errors`
                            : active.finding_count
                              ? "Review findings"
                              : "No findings"}
                        </span>
                      </div>
                      <div className="trace-meta">
                        <span>
                          <Layers size={14} />
                          {active.span_count} spans
                        </span>
                        <span>
                          <Clock3 size={14} />
                          {active.duration_ms.toFixed(0)} ms
                        </span>
                        <span>
                          {active.has_usage
                            ? `${active.tokens} tokens reported`
                            : "Token usage unavailable"}
                        </span>
                      </div>
                      <div
                        className="tabs"
                        role="tablist"
                        aria-label="Trace view"
                      >
                        {[
                          ["trace", "Execution path"],
                          ["findings", `Findings (${detail.findings.length})`],
                          ["outcome", "Outcome & checks"],
                        ].map(([k, v]) => (
                          <button
                            role="tab"
                            aria-selected={tab === k}
                            key={k}
                            onClick={() => setTab(k)}
                          >
                            {v}
                          </button>
                        ))}
                      </div>
                      {tab === "trace" && (
                        <>
                          <div className="timeline-head">
                            <span>SPAN / SERVICE</span>
                            <span>EXECUTION WINDOW</span>
                            <span>TIME</span>
                          </div>
                          <div className="timeline">
                            {detail.spans.map((s) => {
                              let depth = 0,
                                p = s.parent_id;
                              const seen = new Set<string>();
                              while (p && depth < 7 && !seen.has(p)) {
                                seen.add(p);
                                depth++;
                                p =
                                  detail.spans.find((x) => x.span_id === p)
                                    ?.parent_id || null;
                              }
                              const duration = (s.end_ns - s.start_ns) / 1e6;
                              const offset =
                                (s.start_ns - active.started_ns) / 1e6;
                              return (
                                <button
                                  key={s.span_id}
                                  className={
                                    "span-row " +
                                    (s.span_id === spanId ? "focused" : "")
                                  }
                                  onClick={() => setSpanId(s.span_id)}
                                >
                                  <div
                                    className="span-label"
                                    style={{
                                      paddingLeft: Math.min(depth, 4) * 11,
                                    }}
                                  >
                                    <span
                                      className={
                                        "span-node " +
                                        (s.status === "ERROR"
                                          ? "bad"
                                          : s.attributes["eval.passed"] ===
                                              false
                                            ? "warn"
                                            : "")
                                      }
                                    />
                                    <div>
                                      <span>{s.name}</span>
                                      <small>
                                        {String(
                                          s.resource["service.name"] || "",
                                        )}
                                      </small>
                                    </div>
                                  </div>
                                  <div className="span-track">
                                    <span
                                      className={
                                        s.status === "ERROR"
                                          ? "bar error"
                                          : s.name.startsWith("model")
                                            ? "bar model"
                                            : "bar"
                                      }
                                      style={{
                                        left: `${(offset / Math.max(active.duration_ms, 0.01)) * 100}%`,
                                        width: `${Math.max(0.4, (duration / Math.max(active.duration_ms, 0.01)) * 100)}%`,
                                      }}
                                    />
                                  </div>
                                  <span className="span-time">
                                    {duration.toFixed(1)} ms
                                  </span>
                                </button>
                              );
                            })}
                          </div>
                          {currentSpan && (
                            <div className="span-detail">
                              <div className="span-detail-head">
                                <strong>{currentSpan.name}</strong>
                                <span>{currentSpan.status}</span>
                              </div>
                              <div className="span-ids">
                                <span>
                                  Span <code>{currentSpan.span_id}</code>
                                </span>
                                <span>
                                  Parent{" "}
                                  <code>{currentSpan.parent_id || "root"}</code>
                                </span>
                              </div>
                              <pre>
                                {JSON.stringify(
                                  currentSpan.attributes,
                                  null,
                                  2,
                                )}
                              </pre>
                            </div>
                          )}
                        </>
                      )}
                      {tab === "findings" && (
                        <div className="findings">
                          {detail.findings.length ? (
                            detail.findings.map((f, i) => (
                              <button
                                key={i}
                                className="finding"
                                onClick={() => {
                                  setSpanId(f.span_id);
                                  setTab("trace");
                                }}
                              >
                                <CircleAlert size={17} />
                                <div>
                                  <strong>{f.title}</strong>
                                  <p>{f.detail}</p>
                                  <small>
                                    Inspect source span{" "}
                                    <ArrowUpRight size={12} />
                                  </small>
                                </div>
                              </button>
                            ))
                          ) : (
                            <div className="empty">
                              <ShieldCheck size={28} />
                              <strong>No rule-based findings</strong>
                              <p>
                                This is not proof of general answer correctness.
                                Add domain-specific evaluations.
                              </p>
                            </div>
                          )}
                        </div>
                      )}
                      {tab === "outcome" && (
                        <div className="outcome-view">
                          {detail.run ? (
                            <>
                              <span className="pill neutral">
                                {detail.run.runtime === "scripted"
                                  ? "SCRIPTED RESPONSE"
                                  : "LOCAL MODEL RESPONSE"}
                              </span>
                              <p className="answer-text">{detail.run.answer}</p>
                              <div className="checks">
                                {detail.run.assertions.map((a) => (
                                  <div key={a.name}>
                                    <span>{a.name}</span>
                                    <strong
                                      className={
                                        a.passed ? "text-good" : "text-bad"
                                      }
                                    >
                                      {a.passed ? "Pass" : "Fail"}
                                    </strong>
                                  </div>
                                ))}
                              </div>
                              <p className="subtle">
                                Assertions are tailored to this synthetic
                                workload. They do not measure production
                                customer outcomes.
                              </p>
                            </>
                          ) : (
                            <div className="empty">
                              External trace. No linked demo evaluation.
                            </div>
                          )}
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="empty inspector-empty">
                      <Workflow size={35} />
                      <strong>Select an execution</strong>
                      <p>
                        Explore its spans, evidence, and evaluation results.
                      </p>
                    </div>
                  )}
                </section>
              </div>
            </>
          )}
          {page === "experiments" && (
            <>
              <section className="experiment-intro">
                <div>
                  <span className="pill neutral">INCIDENT-FIXTURES-V1</span>
                  <h2>One dataset. Two implementations.</h2>
                  <p>
                    Four authored scenarios run against baseline and controlled
                    workflows. Responses are deterministic fixtures; timings and
                    spans come from actual execution.
                  </p>
                </div>
                <button
                  className="primary"
                  disabled={busy}
                  onClick={() => void evaluate()}
                >
                  {busy ? (
                    <LoaderCircle className="spin" size={16} />
                  ) : (
                    <FlaskConical size={16} />
                  )}{" "}
                  {busy ? "Evaluating…" : "Run comparison"}
                </button>
              </section>
              {experiments.length > 0 ? (
                <>
                  <div className="comparison">
                    {["baseline", "guarded"].map((v) => (
                      <div key={v}>
                        <span>
                          {v === "baseline" ? "Baseline" : "With controls"}
                        </span>
                        <strong>
                          {experiments[0].summary[v].passed}
                          <small> / {experiments[0].summary[v].total}</small>
                        </strong>
                        <p>Scenarios passing all assertions</p>
                        <div className="progress-track">
                          <span
                            style={{
                              width:
                                (100 * experiments[0].summary[v].passed) /
                                  experiments[0].summary[v].total +
                                "%",
                            }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                  <section className="experiment-table">
                    <div className="panel-head">
                      <h2>Latest comparison</h2>
                      <code>{experiments[0].id.slice(0, 8)}</code>
                    </div>
                    <table>
                      <thead>
                        <tr>
                          <th>Scenario</th>
                          <th>Implementation</th>
                          <th>Checks</th>
                          <th>Duration</th>
                          <th>Trace</th>
                        </tr>
                      </thead>
                      <tbody>
                        {experiments[0].rows.map((r) => (
                          <tr key={r.id}>
                            <td>{pretty(r.scenario)}</td>
                            <td>
                              {r.variant === "guarded"
                                ? "With controls"
                                : "Baseline"}
                            </td>
                            <td>
                              <span
                                className={
                                  "pill " + (r.passed ? "success" : "danger")
                                }
                              >
                                {r.passed ? "Pass" : "Fail"}
                              </span>
                            </td>
                            <td>{r.duration_ms.toFixed(0)} ms</td>
                            <td>
                              <button
                                className="text-button"
                                onClick={() => {
                                  setSelected(r.trace_id);
                                  setPage("traces");
                                }}
                              >
                                Inspect <ArrowUpRight size={13} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </section>
                  <p className="footnote">{experiments[0].limitations}</p>
                </>
              ) : (
                <div className="empty">
                  <FlaskConical size={32} />
                  <strong>No experiments yet</strong>
                  <p>Run the comparison to create a measured report.</p>
                </div>
              )}
            </>
          )}
          {page === "connect" && (
            <div className="connect-grid">
              <section className="connect-card">
                <Terminal size={24} />
                <h2>Python instrumentation</h2>
                <p>
                  The bundled exporter removes non-allowlisted attributes before
                  transport.
                </p>
                <pre>{`from agentscope.telemetry import create_tracer\n\ntracer, provider, exporter = create_tracer(\n    service="my-agent",\n    endpoint="http://127.0.0.1:8765/v1/traces",\n)\nwith tracer.start_as_current_span("agent.run"):\n    with tracer.start_as_current_span("tool.lookup"):\n        pass\nprovider.shutdown()`}</pre>
              </section>
              <section className="connect-card">
                <Plug size={24} />
                <h2>OTLP/HTTP collector</h2>
                <p>
                  Accepts protobuf and JSON traces at <code>/v1/traces</code>.
                  Existing SDKs can use this collector endpoint.
                </p>
                <dl>
                  <dt>Collector</dt>
                  <dd>http://127.0.0.1:8765/v1/traces</dd>
                  <dt>Trace context</dt>
                  <dd>W3C traceparent; parent IDs and links</dd>
                  <dt>Storage</dt>
                  <dd>SQLite WAL; duplicate deliveries upsert</dd>
                  <dt>Scope</dt>
                  <dd>Local development; no authentication or tenancy</dd>
                </dl>
                <p className="subtle">
                  Third-party exporters may transmit raw data before
                  collector-side filtering. Configure source-side redaction.
                  Application spans show execution paths, not a provider’s
                  internal reasoning or network route.
                </p>
              </section>
              <section className="connect-card full">
                <ShieldCheck size={24} />
                <h2>Clear deployment boundaries</h2>
                <p>
                  This release runs the collector, database, dashboard, and
                  fixture agents locally. Ollama inference uses your local
                  model. The MCP demonstration propagates context across a real
                  subprocess. Cloud exporters require an explicit opt-in; a
                  multicloud deployment is not included.
                </p>
                <p className="subtle">
                  Keep the API on loopback. Production needs identity, tenant
                  isolation, quotas, retention, durable ingestion,
                  authentication, and transport security.
                </p>
              </section>
            </div>
          )}
          <footer>
            AgentScope / Independent engineering portfolio{" "}
            <span>Observable behavior. Reproducible evidence.</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
function Metric({
  icon,
  title,
  value,
  sub,
}: {
  icon: React.ReactNode;
  title: string;
  value: string;
  sub: string;
}) {
  return (
    <div className="metric">
      <div>
        {title}
        {icon}
      </div>
      <strong>{value}</strong>
      <small>{sub}</small>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
