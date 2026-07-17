import { Suspense, lazy, useState } from "react";
import { api, type Approval, type ApprovalCall, type Decision } from "../api";
import { Badge, Icon, tierLabel, tierStatus } from "./Badge";
import { Customer360 } from "./Customer360";

const LiveCall = lazy(() => import("./LiveCall"));

type Outcome = { kind: "preview" | "counterfactual"; body: React.ReactNode };

/** The stored citation is the router's reason with the retrieved clause appended as
 *  `... [policy: <clause>]`, and the clause is raw markdown. Shown verbatim, a human
 *  approver reads asterisks and a bracket-soup. Split it: the *reason* is the decision,
 *  the *clause* is the evidence. */
function splitCitation(raw: string): { reason: string; clause: string | null } {
  const m = raw.match(/^(.*?)\s*\[policy:\s*([\s\S]*)\]\s*$/);
  const strip = (s: string) => s.replace(/\*\*|__|[*`]/g, "").trim();
  if (!m) return { reason: strip(raw), clause: null };
  return { reason: strip(m[1]), clause: strip(m[2]) };
}

function ApprovalCard({
  approval,
  onDecided,
  notify,
  role,
  operatorApprovalLimit,
}: {
  approval: Approval;
  onDecided: (msg: string, ok: boolean) => void;
  notify: (msg: string, ok?: boolean) => void;
  role: string;
  operatorApprovalLimit: number;
}) {
  const [args, setArgs] = useState(() => JSON.stringify(approval.tool_args, null, 2));
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [call, setCall] = useState<ApprovalCall | null>(null);
  const [busy, setBusy] = useState(false);
  const amount = Number(approval.tool_args.amount);
  const rawOrderId = approval.tool_args.order_id;
  const orderId = typeof rawOrderId === "number" ? rawOrderId : Number(rawOrderId);
  const exceedsOperatorLimit =
    role === "operator" &&
    (approval.tool_name === "issue_refund" || approval.tool_name === "apply_credit") &&
    Number.isFinite(amount) &&
    amount > operatorApprovalLimit;

  /** Put a human on a call to decide this. Rings a real phone when a SIP trunk is
   *  configured; otherwise we join the same room from the browser. */
  async function callHuman() {
    setBusy(true);
    try {
      const res = await api.approvalCall(approval.id);
      if (res.dialed) {
        notify(`Ringing ${res.phone} — the agent is briefing them now.`);
      } else {
        setCall(res);
        notify("No phone trunk configured — join the approval call right here.");
      }
    } catch (e) {
      notify(String(e), false);
    } finally {
      setBusy(false);
    }
  }

  async function decide(decision: Decision["decision"]) {
    const body: Decision = { decision };
    if (decision === "reject") body.reason = window.prompt("Why are you declining?") || "declined";
    if (decision === "modify") {
      try {
        body.modified_args = JSON.parse(args);
      } catch {
        notify("Modified arguments must be valid JSON.", false);
        return;
      }
    }
    setBusy(true);
    try {
      await api.decide(approval.id, body);
      onDecided(`${approval.tool_name} ${decision}d — the agent resumed.`, decision !== "reject");
    } catch (e) {
      notify(String(e), false);
    } finally {
      setBusy(false);
    }
  }

  async function preview() {
    setBusy(true);
    try {
      const p = await api.preview(approval.id);
      setOutcome({
        kind: "preview",
        body: (
          <>
            <div className="outcome__row">
              <Badge status="good" label="Approve" />
              <span>
                executes · effects <code>{JSON.stringify(p.outcomes.approve.effects ?? {})}</code>
              </span>
            </div>
            <div className="outcome__row">
              <Badge status="critical" label="Decline" />
              <span>no side effect runs; the customer is told</span>
            </div>
          </>
        ),
      });
    } catch (e) {
      notify(String(e), false);
    } finally {
      setBusy(false);
    }
  }

  async function whatIf() {
    setBusy(true);
    setOutcome({ kind: "counterfactual", body: <span>Replaying both branches in a sandbox…</span> });
    try {
      const cf = await api.counterfactual(approval.thread_id);
      const arm = (name: string) => {
        const o = cf.outcomes?.[name];
        return (
          <div className="outcome__row" key={name}>
            <Badge status={name === "approve" ? "good" : "critical"} label={name === "approve" ? "Approve" : "Decline"} />
            <span>
              {o?.reply || "—"} <code>{JSON.stringify(o?.effects ?? {})}</code>
            </span>
          </div>
        );
      };
      setOutcome({
        kind: "counterfactual",
        body: (
          <>
            <div style={{ marginBottom: 8, color: "var(--muted)" }}>
              Both branches were really executed — on a cloned store. Nothing real moved.
            </div>
            {arm("approve")}
            {arm("reject")}
          </>
        ),
      });
    } catch (e) {
      setOutcome(null);
      notify(String(e), false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="card__head">
        <span className="card__tool">{approval.tool_name}</span>
        <Badge status={tierStatus(approval.risk_tier)} label={tierLabel(approval.risk_tier)} />
        {approval.escalated_at && <Badge status="critical" label="overdue" icon="clock" />}
      </div>

      {approval.policy_citation &&
        (() => {
          const { reason, clause } = splitCitation(approval.policy_citation);
          return (
            <div className="citation">
              <strong>Why this needs you</strong>
              {reason}
              {clause && (
                <blockquote className="citation__clause">
                  “{clause}”
                  <cite>refund_policy.md — retrieved at runtime</cite>
                </blockquote>
              )}
            </div>
          );
        })()}

      {Number.isInteger(orderId) && orderId > 0 && <Customer360 orderId={orderId} />}

      <label className="field">Arguments — edit before choosing “Modify”</label>
      <textarea rows={4} value={args} onChange={(e) => setArgs(e.target.value)} spellCheck={false} />

      <div className="meta">
        {approval.thread_id}
        {approval.created_at ? ` · ${new Date(approval.created_at).toLocaleTimeString()}` : ""}
      </div>

      <div className="btns" style={{ marginTop: 12 }}>
        {exceedsOperatorLimit ? (
          <button className="btn" disabled title={`Supervisor approval required above $${operatorApprovalLimit.toFixed(2)}`}>
            Escalate to manager
          </button>
        ) : (
          <button className="btn btn--good" disabled={busy} onClick={() => decide("approve")}>
            Approve
          </button>
        )}
        <button className="btn btn--warning" disabled={busy} onClick={() => decide("modify")}>
          Modify
        </button>
        <button className="btn btn--critical" disabled={busy} onClick={() => decide("reject")}>
          Decline
        </button>
        <button className="btn" disabled={busy} onClick={preview}>
          <Icon name="eye" /> Preview
        </button>
        <button className="btn" disabled={busy} onClick={whatIf}>
          <Icon name="bolt" /> What if?
        </button>
        <button className="btn" disabled={busy || !!call} onClick={callHuman}>
          <Icon name="phone" /> Call a human
        </button>
      </div>

      {call && (
        <div className="outcome" style={{ marginTop: 12 }}>
          <div style={{ marginBottom: 8, color: "var(--muted)" }}>
            The agent is on the line and will read out this action. Say your PIN, then approve or decline.
          </div>
          <Suspense fallback={<div>Joining the approval call…</div>}>
            <LiveCall
              conn={call}
              onHold={false}
              onDisconnected={() => setCall(null)}
              onError={(e) => notify(`Call error: ${e.message}`, false)}
            />
          </Suspense>
        </div>
      )}

      {outcome && <div className="outcome">{outcome.body}</div>}
    </div>
  );
}

export function ApprovalInbox({
  approvals,
  onDecided,
  notify,
  role,
  operatorApprovalLimit,
}: {
  approvals: Approval[];
  onDecided: (msg: string, ok: boolean) => void;
  notify: (msg: string, ok?: boolean) => void;
  role: string;
  operatorApprovalLimit: number;
}) {
  if (approvals.length === 0) {
    return (
      <div className="empty">
        Nothing awaiting approval.
        <div style={{ marginTop: 4, fontSize: 12 }}>
          High-stakes actions pause here — the agent waits until you decide.
        </div>
      </div>
    );
  }
  return (
    <>
      {approvals.map((a) => (
        <ApprovalCard
          key={a.id}
          approval={a}
          onDecided={onDecided}
          notify={notify}
          role={role}
          operatorApprovalLimit={operatorApprovalLimit}
        />
      ))}
    </>
  );
}
