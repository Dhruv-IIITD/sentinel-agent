/* Status badges.
 *
 * The status palette (good / warning / serious / critical) is reserved and fixed
 * in both themes. Two rules from the design system are load-bearing here:
 *   1. a status color NEVER carries meaning alone — every badge pairs it with an
 *      icon AND a text label (on the light surface, `warning` and `serious` sit
 *      below 3:1 contrast by design, so the label is the accessible channel);
 *   2. text wears ink tokens, never the data color — the colored icon beside the
 *      label is what carries identity.
 */
export type Status = "good" | "warning" | "serious" | "critical" | "neutral";

export const STATUS_COLOR: Record<Status, string> = {
  good: "var(--good)",
  warning: "var(--warning)",
  serious: "var(--serious)",
  critical: "var(--critical)",
  neutral: "var(--muted)",
};

const P = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

export function Icon({ name, size = 13 }: { name: Status | "clock" | "undo" | "eye" | "phone" | "bolt"; size?: number }) {
  const c = { width: size, height: size, viewBox: "0 0 24 24", ...P };
  switch (name) {
    case "good":
      return <svg {...c}><path d="M20 6 9 17l-5-5" /></svg>;
    case "critical":
      return <svg {...c}><path d="M18 6 6 18M6 6l12 12" /></svg>;
    case "warning":
      return <svg {...c}><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" /></svg>;
    case "serious":
    case "undo":
      return <svg {...c}><path d="M3 7v6h6" /><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13" /></svg>;
    case "clock":
      return <svg {...c}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>;
    case "eye":
      return <svg {...c}><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /></svg>;
    case "phone":
      return <svg {...c}><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2Z" /></svg>;
    case "bolt":
      return <svg {...c}><path d="M13 2 3 14h9l-1 8 10-12h-9l1-8Z" /></svg>;
    default:
      return <svg {...c}><circle cx="12" cy="12" r="4" /></svg>;
  }
}

export function Badge({ status, label, icon }: { status: Status; label: string; icon?: Parameters<typeof Icon>[0]["name"] }) {
  return (
    <span className="badge">
      <span style={{ color: STATUS_COLOR[status], display: "inline-flex" }}>
        <Icon name={icon ?? status} />
      </span>
      {label}
    </span>
  );
}

/** Risk tiers are a severity scale, so they map onto status — not categorical slots. */
export function tierStatus(tier: string | null): Status {
  switch (tier) {
    case "read":
      return "neutral";
    case "reversible":
      return "good";
    case "dynamic":
      return "warning";
    case "high_stakes":
      return "critical";
    default:
      return "neutral";
  }
}

export function tierLabel(tier: string | null): string {
  return (tier ?? "unknown").replace("_", "-");
}

export function statusOf(status: string): Status {
  switch (status) {
    case "delivered":
    case "issued":
    case "succeeded":
    case "applied":
    case "approved":
      return "good";
    case "in_transit":
    case "processing":
    case "pending":
      return "warning";
    case "cancelled":
    case "failed":
    case "rejected":
    case "reversed":
      return "critical";
    default:
      return "neutral";
  }
}

export function eventStatus(event: string): Status {
  switch (event) {
    case "executed":
      return "good";
    case "rejected":
      return "critical";
    case "compensated":
      return "serious";
    default:
      return "neutral";
  }
}
