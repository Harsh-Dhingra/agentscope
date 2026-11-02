import { useEffect, useState } from "react";
import {
  Search,
  SlidersHorizontal,
  ChevronLeft,
  ChevronRight,
  ArrowUpDown,
  CheckCircle2,
  AlertCircle,
  CircleDashed,
  RotateCcw,
} from "lucide-react";

type Trace = {
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
export function TraceTable({
  traces,
  selected,
  select,
}: {
  traces: Trace[];
  selected: string | null;
  select: (id: string) => void;
}) {
  const [query, setQuery] = useState(""),
    [status, setStatus] = useState("all"),
    [service, setService] = useState("all"),
    [range, setRange] = useState("all"),
    [sort, setSort] = useState("newest"),
    [page, setPage] = useState(0),
    [size, setSize] = useState(25);
  const cutoff =
    range === "all" ? 0 : Date.now() - (range === "24h" ? 24 : 168) * 3600000;
  const filtered = traces
    .filter(
      (t) =>
        `${t.name} ${t.scenario} ${t.service} ${t.trace_id} ${t.runtime} ${t.variant}`
          .toLowerCase()
          .includes(query.toLowerCase()) &&
        (service === "all" || t.service === service) &&
        (status === "all" ||
          (status === "errors"
            ? t.error_count > 0
            : status === "evaluation"
              ? t.evaluation_failed
              : status === "findings"
                ? t.finding_count > 0
                : !t.error_count && !t.finding_count)) &&
        t.started_ns / 1e6 >= cutoff,
    )
    .sort((a, b) =>
      sort === "slowest"
        ? b.duration_ms - a.duration_ms
        : sort === "tokens"
          ? (b.has_usage ? b.tokens : -1) - (a.has_usage ? a.tokens : -1)
          : sort === "oldest"
            ? a.started_ns - b.started_ns
            : b.started_ns - a.started_ns,
    );
  const pages = Math.max(1, Math.ceil(filtered.length / size)),
    current = Math.min(page, pages - 1),
    rows = filtered.slice(current * size, (current + 1) * size);
  useEffect(() => setPage(0), [query, status, service, range, sort, size]);
  const active =
    query || status !== "all" || service !== "all" || range !== "all";
  function reset() {
    setQuery("");
    setStatus("all");
    setService("all");
    setRange("all");
    setPage(0);
  }
  return (
    <section className="trace-workbench" aria-label="Trace results">
      <div className="workbench-heading">
        <div>
          <strong>Traces</strong>
          <span className="count-badge">{filtered.length}</span>
        </div>
        <span>Latest {traces.length} received executions</span>
      </div>
      <div className="trace-search">
        <Search size={15} />
        <input
          aria-label="Search traces"
          placeholder="Search name, service, trace ID…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <span className="search-hint">Search</span>
      </div>
      <div className="trace-filters">
        <SlidersHorizontal size={14} />
        <select
          aria-label="Trace status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="all">All statuses</option>
          <option value="errors">Execution errors</option>
          <option value="findings">With findings</option>
          <option value="evaluation">Evaluation failed</option>
          <option value="clear">No findings</option>
        </select>
        <select
          aria-label="Trace service"
          value={service}
          onChange={(e) => setService(e.target.value)}
        >
          <option value="all">All services</option>
          {[...new Set(traces.map((t) => t.service))].sort().map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <select
          aria-label="Trace time range"
          value={range}
          onChange={(e) => setRange(e.target.value)}
        >
          <option value="all">All loaded time</option>
          <option value="24h">Last 24 hours</option>
          <option value="7d">Last 7 days</option>
        </select>
        {active && (
          <button
            className="icon-control"
            title="Clear filters"
            aria-label="Clear trace filters"
            onClick={reset}
          >
            <RotateCcw size={14} />
          </button>
        )}
      </div>
      <div className="result-sort">
        <span>{filtered.length} matching · filters apply to loaded traces</span>
        <label>
          <ArrowUpDown size={12} />
          <select
            aria-label="Sort traces"
            value={sort}
            onChange={(e) => setSort(e.target.value)}
          >
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
            <option value="slowest">Highest latency</option>
            <option value="tokens">Most tokens</option>
          </select>
        </label>
      </div>
      <div className="trace-table-scroll">
        <table className="trace-table">
          <thead>
            <tr>
              <th scope="col">Execution</th>
              <th scope="col">Status</th>
              <th scope="col">Latency</th>
              <th scope="col">Tokens</th>
              <th scope="col">Started</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t, index) => (
              <tr
                key={t.trace_id}
                className={selected === t.trace_id ? "is-selected" : ""}
                onClick={() => select(t.trace_id)}
              >
                <td>
                  <button
                    className="trace-open"
                    aria-label={`Inspect trace ${t.trace_id}`}
                    aria-pressed={selected === t.trace_id}
                    onClick={() => select(t.trace_id)}
                    onKeyDown={(e) => {
                      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                        e.preventDefault();
                        const next = Math.max(
                          0,
                          Math.min(
                            rows.length - 1,
                            index + (e.key === "ArrowDown" ? 1 : -1),
                          ),
                        );
                        select(rows[next].trace_id);
                        e.currentTarget
                          .closest("tbody")
                          ?.querySelectorAll<HTMLButtonElement>(".trace-open")
                          [next]?.focus();
                      }
                    }}
                  >
                    <span className="execution-symbol">
                      {t.error_count ? (
                        <AlertCircle size={15} />
                      ) : (
                        <CircleDashed size={15} />
                      )}
                    </span>
                    <span>
                      <strong>{t.name}</strong>
                      <small>{t.service}</small>
                    </span>
                  </button>
                  <code className="row-id">
                    {t.trace_id.slice(0, 12)} · {t.span_count} spans
                  </code>
                </td>
                <td>
                  <span
                    className={
                      "table-status " +
                      (t.error_count
                        ? "error"
                        : t.finding_count
                          ? "review"
                          : "clean")
                    }
                  >
                    {t.error_count ? (
                      <AlertCircle size={12} />
                    ) : t.finding_count ? (
                      <CircleDashed size={12} />
                    ) : (
                      <CheckCircle2 size={12} />
                    )}{" "}
                    {t.error_count
                      ? "Error"
                      : t.finding_count
                        ? "Review"
                        : "Clear"}
                  </span>
                </td>
                <td className="numeric">
                  {t.duration_ms >= 1000
                    ? `${(t.duration_ms / 1000).toFixed(2)} s`
                    : `${t.duration_ms.toFixed(0)} ms`}
                  <span className="latency-track">
                    <i
                      style={{
                        width: `${Math.max(2, Math.min(100, (t.duration_ms / Math.max(...traces.map((x) => x.duration_ms), 1)) * 100))}%`,
                      }}
                    />
                  </span>
                </td>
                <td
                  className="numeric"
                  title={
                    t.has_usage
                      ? "Reported token usage"
                      : "Token usage unavailable"
                  }
                >
                  {t.has_usage ? t.tokens.toLocaleString() : "—"}
                </td>
                <td className="started-cell">
                  <time title={new Date(t.started_ns / 1e6).toISOString()}>
                    {new Date(t.started_ns / 1e6).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </time>
                  <small>
                    {new Date(t.started_ns / 1e6).toLocaleDateString([], {
                      month: "short",
                      day: "numeric",
                    })}
                  </small>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && (
          <div className="empty">
            <Search size={24} />
            <strong>
              {traces.length ? "No matching traces" : "No traces received yet"}
            </strong>
            <p>
              {traces.length
                ? "Adjust your filters to explore more executions."
                : "Connect an agent or run a demo workload to begin."}
            </p>
            {active && (
              <button className="secondary" onClick={reset}>
                Clear filters
              </button>
            )}
          </div>
        )}
      </div>
      <div className="table-footer">
        <label>
          Rows{" "}
          <select
            aria-label="Rows per page"
            value={size}
            onChange={(e) => setSize(Number(e.target.value))}
          >
            <option value={25}>25</option>
            <option value={50}>50</option>
          </select>
        </label>
        <span>
          {filtered.length ? current * size + 1 : 0}–
          {Math.min((current + 1) * size, filtered.length)} of {filtered.length}
        </span>
        <div>
          <button
            aria-label="Previous trace page"
            disabled={current === 0}
            onClick={() => setPage(current - 1)}
          >
            <ChevronLeft size={15} />
          </button>
          <span>
            {current + 1} / {pages}
          </span>
          <button
            aria-label="Next trace page"
            disabled={current === pages - 1}
            onClick={() => setPage(current + 1)}
          >
            <ChevronRight size={15} />
          </button>
        </div>
      </div>
    </section>
  );
}
