import { useCallback, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { CallPanel } from "../components/CallPanel";
import { Icon } from "../components/Badge";

type Toast = { id: number; msg: string; ok: boolean };

export function HelpCenter() {
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

  return (
    <div className="help-surface">
      <header className="help-topbar">
        <span className="mark">
          <Icon name="phone" size={14} />
        </span>
        <span className="brand">HITL Help</span>
        <div className="spacer" />
        <Link className="surface-link surface-link--quiet" to="/">Staff sign in</Link>
      </header>

      <main className="help-page">
        <section className="help-hero">
          <div className="help-hero__eyebrow">Customer support</div>
          <h1>How can we help?</h1>
          <p>
            Talk or type to our support agent about an order. If your request needs a
            person, the agent will pause safely while the support team reviews it.
          </p>
        </section>

        <div className="help-call">
          <CallPanel
            notify={notify}
            title="Talk to support"
          />
        </div>

        <div className="help-promises" aria-label="Support service details">
          <div>
            <strong>Have your order number ready</strong>
            <span>We’ll use it to find your purchase and verify your request.</span>
          </div>
          <div>
            <strong>A human stays in control</strong>
            <span>Refunds and other sensitive actions pause for staff review.</span>
          </div>
        </div>
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
    </div>
  );
}
