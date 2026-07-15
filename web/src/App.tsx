import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Approval, type AuditRow, type Metrics } from "./api";
import { ActivityTimeline } from "./components/ActivityTimeline";
import { ApprovalInbox } from "./components/ApprovalInbox";
import { Badge, Icon } from "./components/Badge";
import { CallPanel } from "./components/CallPanel";
import { Operations } from "./components/Operations";
import { StatTiles } from "./components/StatTiles";
import { StorePanel } from "./components/StorePanel";

type Toast = { id: number; msg: string; ok: boolean };

const POLL_MS = 2000;

export default function App() {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [online, setOnline] = useState(true);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const notify = useCallback((msg: string, ok = true) => {
    const id = nextId.current++;
    setToasts((t) => [...t, { id, msg, ok }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [a, e, m] = await Promise.all([api.approvals(), api.audit(), api.metrics()]);
      setApprovals(a);
      setAudit(e);
      setMetrics(m);
      setOnline(true);
    } catch {
      setOnline(false);
    }
  }, []);

  // The queue is driven by a live call, so poll rather than wait for a user action.
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, POLL_MS);
    return () => clearInterval(t);
  }, [refresh]);

  const onDecided = useCallback(
    (msg: string, ok: boolean) => {
      notify(msg, ok);
      refresh();
    },
    [notify, refresh],
  );

  const onReverse = useCallback(
    async (key: string) => {
      if (!window.confirm("Reverse this action? The compensating operation runs for real.")) return;
      try {
        await api.compensate(key, "reversed from the console");
        notify("Action reversed.", true);
        refresh();
      } catch (e) {
        notify(String(e), false);
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
          HITL Agent <small>· voice support console</small>
        </span>
        <div className="spacer" />
        {approvals.length > 0 && (
          <Badge status="warning" label={`${approvals.length} awaiting approval`} icon="clock" />
        )}
        <span className="live">
          <span className="pulse" style={{ background: online ? "var(--good)" : "var(--critical)" }} />
          {online ? "Live" : "Backend unreachable"}
        </span>
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

        <div className="grid">
          <CallPanel approvals={approvals} notify={notify} onActivity={refresh} />

          <section className="panel">
            <div className="panel__head">
              <span className="panel__title">Approval queue</span>
              <div className="spacer" />
              <span className="live">
                <span className="pulse" />
                auto-refreshing
              </span>
            </div>
            <div className="panel__body">
              <ApprovalInbox approvals={approvals} onDecided={onDecided} notify={notify} />
            </div>
          </section>
        </div>

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
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.ok ? "toast--good" : "toast--critical"}`}>
            {t.msg}
          </div>
        ))}
      </div>
    </>
  );
}
