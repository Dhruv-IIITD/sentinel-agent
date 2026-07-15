import type { Approval, AuditRow } from "../api";
import { Icon, STATUS_COLOR, type Status } from "./Badge";

type Tile = { label: string; value: number; status: Status; note: string; icon?: Parameters<typeof Icon>[0]["name"] };

/** Stat-tile contract: sentence-case label, semibold value in proportional figures
 *  (tabular-nums is for columns that must align, not for display numbers). The
 *  colored dot + icon carries identity; the text stays in ink tokens. */
export function StatTiles({ approvals, audit }: { approvals: Approval[]; audit: AuditRow[] }) {
  const count = (e: string) => audit.filter((a) => a.event_type === e).length;

  const tiles: Tile[] = [
    { label: "Awaiting a human", value: approvals.length, status: "warning", note: "paused mid-flight", icon: "clock" },
    { label: "Actions executed", value: count("executed"), status: "good", note: "exactly once", icon: "good" },
    { label: "Declined by a human", value: count("rejected"), status: "critical", note: "no side effect ran", icon: "critical" },
    { label: "Reversed", value: count("compensated"), status: "serious", note: "compensating action", icon: "undo" },
  ];

  return (
    <div className="stats">
      {tiles.map((t) => (
        <div className="tile" key={t.label}>
          <div className="tile__label">
            <span className="tile__dot" style={{ background: STATUS_COLOR[t.status] }} />
            {t.label}
          </div>
          <div className="tile__value">{t.value.toLocaleString()}</div>
          <div className="tile__note">{t.note}</div>
        </div>
      ))}
    </div>
  );
}
