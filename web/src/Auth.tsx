import { useEffect, useState, type ReactNode } from "react";
import {
  Activity,
  KeyRound,
  ShieldCheck,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";
import { request, setCsrfToken } from "./http";

export type Session = {
  authenticated: boolean;
  mode: string;
  configured?: boolean;
  tenant: string;
  subject: string;
  role: string;
  permissions: string[];
  csrf_token?: string;
};
export function AuthGate({
  children,
}: {
  children: (session: Session, logout: () => Promise<void>) => ReactNode;
}) {
  const [session, setSession] = useState<Session | null>(null),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [key, setKey] = useState(""),
    [error, setError] = useState(""),
    [configured, setConfigured] = useState(true);
  function accept(profile: Session) {
    setCsrfToken(profile.csrf_token || "");
    setConfigured(profile.configured !== false);
    setSession(profile.authenticated ? profile : null);
  }
  async function refresh() {
    setLoading(true);
    setError("");
    try {
      accept(await request<Session>("/auth/session"));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void refresh();
    const expired = () => {
      setCsrfToken("");
      setSession(null);
      setError("Your session expired or was revoked. Sign in again.");
    };
    window.addEventListener("agentscope-session-expired", expired);
    return () =>
      window.removeEventListener("agentscope-session-expired", expired);
  }, []);
  async function login() {
    setBusy(true);
    setError("");
    try {
      const profile = await request<Session>("/auth/login", {
        api_key: key.trim(),
      });
      setKey("");
      accept(profile);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function logout() {
    await request("/auth/logout", {});
    setCsrfToken("");
    setSession(null);
    setError("");
  }
  if (session) return <>{children(session, logout)}</>;
  return (
    <main className="login-page">
      <section className="login-card">
        <div className="login-brand">
          <Activity size={26} />
          <span>AgentScope</span>
          <span className="pill neutral">LOCAL</span>
        </div>
        <div className="login-icon">
          <KeyRound size={25} />
        </div>
        <h1>Your workspace. Your access.</h1>
        <p>
          Sign in with a locally issued access key. Your credential determines
          your tenant and permissions.
        </p>
        {error && (
          <p className="error-banner" role="alert">
            {error}
          </p>
        )}
        {loading ? (
          <div className="work-status">
            <LoaderCircle size={18} className="spin" />
            Checking session…
          </div>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void login();
            }}
          >
            <label htmlFor="access-key">Access key</label>
            <input
              id="access-key"
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={key}
              onChange={(e) => setKey(e.target.value)}
              required
              placeholder="Paste your access key"
            />
            <button
              className="primary"
              type="submit"
              disabled={busy || !key.trim()}
            >
              {busy ? (
                <LoaderCircle size={17} className="spin" />
              ) : (
                <ShieldCheck size={17} />
              )}{" "}
              {busy ? "Signing in…" : "Open workspace"}
            </button>
          </form>
        )}
        {!configured && (
          <div className="login-setup">
            <strong>First-time setup</strong>
            <p>Provision local credentials from the project directory:</p>
            <code>python -m agentscope.identity init</code>
            <p>
              Keys are saved to <code>data/access-keys.json</code>. Choose the
              operator key to run workloads, or the reviewer key to review
              pending changes.
            </p>
          </div>
        )}
        <div className="login-footnote">
          <ShieldCheck size={16} />
          <p>
            The browser uses a revocable HttpOnly session. Access keys are not
            saved in browser storage.
          </p>
        </div>
        <button
          className="login-refresh"
          onClick={() => void refresh()}
          disabled={loading}
        >
          <RefreshCw size={13} /> Check connection
        </button>
      </section>
    </main>
  );
}

type Audit = {
  id: string;
  created_at: number;
  subject: string;
  role: string;
  tenant: string;
  method: string;
  route: string;
  status: number;
};
export function AccessPanel({ session }: { session: Session }) {
  const [events, setEvents] = useState<Audit[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function refresh() {
    setBusy(true);
    try {
      setEvents(await request<Audit[]>("/access/audit"));
      setError("");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    void refresh();
  }, []);
  return (
    <>
      <section className="platform-intro">
        <div>
          <span className="pill neutral">IDENTITY / ACCESS</span>
          <h2>Access follows the credential.</h2>
          <p>
            Each credential is bound to one tenant and one role. The server
            chooses storage from that binding; request headers and trace
            metadata cannot select another tenant.
          </p>
        </div>
        <div className="identity-summary">
          <small>Current workspace</small>
          <strong>{session.tenant}</strong>
          <span>
            {session.subject} · {session.role}
          </span>
        </div>
      </section>
      <div className="access-role-grid">
        {[
          ["Viewer", "Inspect traces, reports, and tenant audit records."],
          [
            "Operator",
            "Run workloads, submit tools, analyze windows, and propose changes.",
          ],
          [
            "Reviewer",
            "Approve a different principal’s proposals, promote, and roll back.",
          ],
          ["Collector", "Write telemetry only. No dashboard access."],
        ].map(([name, description]) => (
          <section className="version-card" key={name}>
            <h3>{name}</h3>
            <p>{description}</p>
          </section>
        ))}
      </div>
      <div className="method-note">
        <strong>Credential administration</strong>
        <p>
          Credentials are issued and revoked through the local CLI. Revocation
          invalidates associated browser sessions on the next request. Keys are
          never listed in this dashboard. This local identity registry is not
          enterprise SSO or proof of a person’s identity.
        </p>
      </div>
      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}
      <section className="policy-events release-results">
        <div className="panel-head">
          <h2>Tenant access audit</h2>
          <button
            className="secondary"
            disabled={busy}
            onClick={() => void refresh()}
          >
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
        {events.length ? (
          events.map((e) => (
            <article className="access-event" key={e.id}>
              <span
                className={"pill " + (e.status < 400 ? "success" : "danger")}
              >
                {e.status}
              </span>
              <div>
                <strong>
                  {e.subject} <small>· {e.role}</small>
                </strong>
                <code>
                  {e.method} {e.route}
                </code>
              </div>
              <time>{new Date(e.created_at * 1000).toLocaleString()}</time>
            </article>
          ))
        ) : (
          <div className="empty">
            <ShieldCheck size={28} />
            <strong>No recorded mutations</strong>
            <p>Authenticated changes and denied writes will appear here.</p>
          </div>
        )}
      </section>
      <div className="method-note">
        <strong>Isolation boundary</strong>
        <p>
          Tenant data uses separate SQLite files inside one application process.
          This protects API access boundaries; it is not operating-system
          isolation, independent encryption keys, or tamper-evident audit
          storage. Synthetic tools and local rollout limits still apply.
        </p>
      </div>
    </>
  );
}
