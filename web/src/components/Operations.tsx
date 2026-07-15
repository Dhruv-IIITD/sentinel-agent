import type { Metrics } from "../api";

const dash = "—";

function pct(v: number | null): string {
  return v === null ? dash : `${Math.round(v * 100)}%`;
}

function secs(v: number | null): string {
  if (v === null) return dash;
  return v < 60 ? `${v.toFixed(1)}s` : `${Math.round(v / 60)}m`;
}

/** The numbers that decide whether a human-in-the-loop system is working.
 *
 *  Everything here is derived from the audit log + approval queue, so it can't drift
 *  from what actually happened. Nulls render as an em-dash rather than a fake zero:
 *  "no data yet" and "zero percent" are very different claims.
 */
export function Operations({ metrics }: { metrics: Metrics | null }) {
  if (!metrics) return <div className="empty">No activity yet.</div>;

  const autonomy = metrics.autonomy_rate;
  const { auto_executed, executed_after_approval, declined_by_human } = metrics.actions;
  const concluded = auto_executed + executed_after_approval + declined_by_human;

  return (
    <div className="ops">
      <div>
        <div className="ops__label">Handled without a human</div>
        <div className="ops__value">{pct(autonomy)}</div>
        <div className="meter">
          <div className="meter__fill" style={{ width: `${(autonomy ?? 0) * 100}%` }} />
        </div>
        <div className="ops__sub">
          {auto_executed} of {concluded} action{concluded === 1 ? "" : "s"} auto-executed
        </div>
      </div>

      <div>
        <div className="ops__label">Caller held for</div>
        <div className="ops__value">{secs(metrics.time_to_decision_s.p50)}</div>
        <div className="ops__sub">p95 {secs(metrics.time_to_decision_s.p95)}</div>
      </div>

      <div>
        <div className="ops__label">Agent overruled</div>
        <div className="ops__value">{pct(metrics.override_rate)}</div>
        <div className="ops__sub">
          {metrics.approvals.rejected} declined · {metrics.approvals.modified} edited
        </div>
      </div>

      <div>
        <div className="ops__label">Tool latency</div>
        <div className="ops__value">
          {metrics.tool_latency_ms.p50 === null ? dash : `${Math.round(metrics.tool_latency_ms.p50)}ms`}
        </div>
        <div className="ops__sub">
          p95{" "}
          {metrics.tool_latency_ms.p95 === null
            ? dash
            : `${Math.round(metrics.tool_latency_ms.p95)}ms`}
        </div>
      </div>
    </div>
  );
}
