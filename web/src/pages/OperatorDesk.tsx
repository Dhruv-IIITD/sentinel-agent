import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  AUTH_CLEARED_EVENT,
  clearAccessToken,
  setAccessToken,
  type Approval,
  type AuditRow,
  type AuthUser,
  type Metrics,
} from "../api";
import { ActivityTimeline } from "../components/ActivityTimeline";
import { ApprovalInbox } from "../components/ApprovalInbox";
import { Badge, Icon } from "../components/Badge";
import { Login } from "../components/Login";
import { Operations } from "../components/Operations";
import { StatTiles } from "../components/StatTiles";
import { StorePanel } from "../components/StorePanel";
import { useApprovalEvents } from "../useApprovalEvents";

type Toast = { id: number; msg: string; ok: boolean };

const POLL_MS = 20_000;

function ConnectionIndicator({ connected }: { connected: boolean }) {
  return (
    <span className="live">
      <span
        className="pulse"
        style={{
          animation: connected ? undefined : "none",
          background: connected ? "var(--good)" : "var(--muted)",
        }}
      />
      {connected ? "live" : "reconnecting…"}
    </span>
  );
}

function Desk({ currentUser, onLogout }: { currentUser: AuthUser; onLogout: () => void }) {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const notify = useCallback((msg: string, ok = true) => {
    const id = nextId.current++;
    setToasts((current) => [...current, { id, msg, ok }]);
    setTimeout(
      () => setToasts((current) => current.filter((toast) => toast.id !== id)),
      4000,
    );
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [nextApprovals, nextAudit, nextMetrics] = await Promise.all([
        api.approvals(),
        api.audit(),
        api.metrics(),
      ]);
      setApprovals(nextApprovals);
      setAudit(nextAudit);
      setMetrics(nextMetrics);
    } catch {
      // Keep the last good snapshot; the socket and safety poll both keep retrying.
    }
  }, []);

  const socketConnected = useApprovalEvents(() => {
    void refresh();
  });

  // Initial state plus a slow safety net for deployments where WebSockets are unavailable.
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(refresh, POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const onDecided = useCallback(
    (msg: string, ok: boolean) => {
      notify(msg, ok);
      void refresh();
    },
    [notify, refresh],
  );

  const onReverse = useCallback(
    async (key: string) => {
      if (!window.confirm("Reverse this action? The compensating operation runs for real.")) return;
      try {
        await api.compensate(key, "reversed from the console");
        notify("Action reversed.", true);
        void refresh();
      } catch (error) {
        notify(String(error), false);
      }
    },
    [notify, refresh],
  );

  return (
    <>
      <header className="topbar">
        <span className="mark">
          <Icon name="phone" size={14} />
        </span>
        <span className="brand">
          HITL Agent <small>· operator desk</small>
        </span>
        <div className="spacer" />
        {approvals.length > 0 && (
          <Badge status="warning" label={`${approvals.length} awaiting approval`} icon="clock" />
        )}
        <ConnectionIndicator connected={socketConnected} />
        <Link className="surface-link" to="/help">Customer view</Link>
        <span className="operator-id">
          <span className="operator-id__email">{currentUser.email}</span>
          <Badge status="neutral" label={currentUser.role} />
        </span>
        <button className="btn btn--sm" type="button" onClick={onLogout}>Logout</button>
      </header>

      <main className="page">
        <StatTiles approvals={approvals} audit={audit} />

        <section className="panel" style={{ marginBottom: 18 }}>
          <div className="panel__head">
            <span className="panel__title">Store</span>
            <div className="spacer" />
            <span className="live">what the caller verifies against</span>
          </div>
          <div className="panel__body">
            <StorePanel onChange={refresh} notify={notify} />
          </div>
        </section>

        <section className="panel">
          <div className="panel__head">
            <span className="panel__title">Approval queue</span>
            <div className="spacer" />
            <ConnectionIndicator connected={socketConnected} />
          </div>
          <div className="panel__body">
            <ApprovalInbox
              approvals={approvals}
              onDecided={onDecided}
              notify={notify}
              role={currentUser.role}
              operatorApprovalLimit={currentUser.operator_approval_limit}
            />
          </div>
        </section>

        <section className="panel" style={{ marginTop: 18 }}>
          <div className="panel__head">
            <span className="panel__title">Operations</span>
            <div className="spacer" />
            <span className="live">derived from the audit log — cannot drift</span>
          </div>
          <div className="panel__body">
            <Operations metrics={metrics} />
          </div>
        </section>

        <section className="panel" style={{ marginTop: 18 }}>
          <div className="panel__head">
            <span className="panel__title">Activity</span>
            <div className="spacer" />
            <span className="live">every action, logged</span>
          </div>
          <div className="panel__body">
            <ActivityTimeline audit={audit} onReverse={onReverse} />
          </div>
        </section>
      </main>

      <div className="toasts">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`toast ${toast.ok ? "toast--good" : "toast--critical"}`}
          >
            {toast.msg}
          </div>
        ))}
      </div>
    </>
  );
}

export function OperatorDesk() {
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);

  const loadSession = useCallback(async () => {
    try {
      setCurrentUser(await api.me());
    } catch {
      setCurrentUser(null);
    } finally {
      setCheckingSession(false);
    }
  }, []);

  useEffect(() => {
    const signedOut = () => {
      setCurrentUser(null);
      setCheckingSession(false);
    };
    window.addEventListener(AUTH_CLEARED_EVENT, signedOut);
    void loadSession();
    return () => window.removeEventListener(AUTH_CLEARED_EVENT, signedOut);
  }, [loadSession]);

  const login = useCallback(async (email: string, password: string) => {
    const result = await api.login(email, password);
    setAccessToken(result.access_token);
    try {
      setCurrentUser(await api.me());
    } catch (error) {
      clearAccessToken();
      throw error;
    }
  }, []);

  const logout = useCallback(() => {
    clearAccessToken();
    setCheckingSession(true);
    void loadSession();
  }, [loadSession]);

  if (checkingSession) {
    return (
      <main className="auth-shell">
        <div className="auth-card auth-card--loading">Checking your session…</div>
      </main>
    );
  }

  if (!currentUser) return <Login onLogin={login} />;
  return <Desk currentUser={currentUser} onLogout={logout} />;
}
