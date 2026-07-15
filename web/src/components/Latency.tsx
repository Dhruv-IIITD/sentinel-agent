import { Badge } from "./Badge";

export type Sample = {
  stt_ms: number;
  llm_ms: number;
  tts_ms: number;
  other_ms: number;
  total_ms: number;
};

/** `total_ms` is LiveKit's own `e2e_latency` — measured, not summed from the legs.
 *  Whatever the three legs don't account for is shown as "Other" rather than hidden,
 *  so the bar always adds up to the number in the hero. */
const SERIES = [
  { key: "stt_ms", label: "Turn detect", color: "var(--series-stt)" },
  { key: "llm_ms", label: "LLM", color: "var(--series-llm)" },
  { key: "tts_ms", label: "Speech", color: "var(--series-tts)" },
  { key: "other_ms", label: "Other", color: "var(--muted)" },
] as const;

/** Nearest-rank percentile — small samples, so no interpolation games. */
function pct(values: number[], q: number): number | null {
  if (!values.length) return null;
  const s = [...values].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.max(0, Math.round(q * s.length + 0.5) - 1))];
}

/** ~1s is the line between "a person" and "a kiosk". */
function verdict(ms: number) {
  if (ms <= 1000) return { status: "good" as const, label: "snappy" };
  if (ms <= 1800) return { status: "warning" as const, label: "sluggish" };
  return { status: "critical" as const, label: "slow" };
}

export function Latency({ samples }: { samples: Sample[] }) {
  if (!samples.length) {
    return (
      <div className="lat">
        <span className="lat__stat" style={{ color: "var(--muted)" }}>
          Latency appears here after the agent's first reply.
        </span>
      </div>
    );
  }

  const last = samples[samples.length - 1];
  const totals = samples.map((s) => s.total_ms);
  const p50 = pct(totals, 0.5);
  const p95 = pct(totals, 0.95);
  const v = verdict(last.total_ms);
  const span = Math.max(1, last.total_ms);

  return (
    <div>
      <div className="lat">
        <div className="lat__hero">
          <span className="lat__ms">{last.total_ms}</span>
          <span className="lat__unit">ms</span>
        </div>
        <Badge status={v.status} label={v.label} />
        <span className="lat__stat">
          p50 <b>{p50}ms</b>
        </span>
        <span className="lat__stat">
          p95 <b>{p95}ms</b>
        </span>
        <span className="lat__stat">
          {samples.length} turn{samples.length === 1 ? "" : "s"}
        </span>
      </div>

      {/* Where the last turn's time actually went. */}
      <div className="stack">
        {SERIES.map((s) => (
          <div
            key={s.key}
            className="stack__seg"
            style={{ background: s.color, width: `${(last[s.key] / span) * 100}%` }}
          />
        ))}
      </div>

      <div className="legend">
        {SERIES.map((s) => (
          <span className="legend__item" key={s.key}>
            <span className="legend__dot" style={{ background: s.color }} />
            {s.label} <span className="legend__val">{last[s.key]}ms</span>
          </span>
        ))}
      </div>

      <div className="ops__sub" style={{ marginTop: 6 }}>
        End of your speech → the agent's first audio, as measured by LiveKit. Tool time
        isn't counted; a pause for human approval isn't latency, it's the product.
      </div>
    </div>
  );
}
