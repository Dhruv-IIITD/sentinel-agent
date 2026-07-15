import { COMPENSABLE, type AuditRow } from "../api";
import { Badge, eventStatus } from "./Badge";

export function ActivityTimeline({
  audit,
  onReverse,
}: {
  audit: AuditRow[];
  onReverse: (key: string) => void;
}) {
  if (audit.length === 0) {
    return <div className="empty">No actions yet. Start a call or send a message.</div>;
  }

  return (
    <div>
      {[...audit].reverse().map((e, i) => {
        // Only an executed, ledger-backed, compensable action can be undone.
        const reversible = e.event_type === "executed" && !!e.idempotency_key && COMPENSABLE.has(e.tool_name ?? "");
        return (
          <div className="event" key={`${e.idempotency_key ?? e.thread_id}-${i}`}>
            <Badge status={eventStatus(e.event_type)} label={e.event_type} />
            <span className="event__tool">{e.tool_name ?? "—"}</span>
            <span className="event__actor">{e.actor}</span>
            <span className="event__thread">{e.thread_id}</span>
            {reversible && (
              <button className="btn btn--sm" onClick={() => onReverse(e.idempotency_key!)}>
                Reverse
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
