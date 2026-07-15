"""Operational metrics — the numbers that actually matter for a human-in-the-loop system.

LangSmith answers "what did the agent *think*". This answers "how is the loop *doing*":

* **Autonomy rate** — the share of actions the agent handled without a human. The whole
  economic argument for the system. Too low and you have built an expensive form; too
  high and the gate probably is not catching anything.
* **Time to decision** — how long an approval sat in the queue. On a voice call this is
  not a dashboard statistic, it is **how long the caller was on hold**, which is why it
  is reported in seconds and why the p95 matters more than the median.
* **Override rate** — how often a human declined or edited what the agent proposed. A
  rising override rate is the earliest signal that the agent's judgement (or the policy)
  has drifted.
* **Reversals** — actions a human undid after the fact. The ones the gate let through
  that it should not have.

All of it is derived from the audit log and the approval queue, so it is true by
construction rather than separately instrumented (and it survives a restart).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request

router = APIRouter(tags=["metrics"])


def _pct(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile. Small samples here, so no interpolation games."""
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(q * len(ordered) + 0.5) - 1))
    return round(ordered[idx], 2)


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


@router.get("/metrics")
async def metrics(request: Request) -> dict:
    store = request.app.state.store
    audit = await store.list_audit(limit=1000)
    approvals = await store.list_approvals()  # every status, not just pending

    executed = [a for a in audit if a.get("event_type") == "executed"]
    auto = sum(1 for a in executed if a.get("actor") == "agent")
    by_human = sum(1 for a in executed if a.get("actor") == "human")
    declined = sum(1 for a in audit if a.get("event_type") == "rejected")
    reversed_ = sum(1 for a in audit if a.get("event_type") == "compensated")

    # Every action that reached a conclusion, whether a human was involved or not.
    concluded = auto + by_human + declined
    autonomy = auto / concluded if concluded else None

    pending = [a for a in approvals if a["status"] == "pending"]
    decided = [a for a in approvals if a["status"] != "pending"]
    rejected = sum(1 for a in decided if a["status"] == "rejected")
    modified = sum(1 for a in decided if a["status"] == "modified")
    override = (rejected + modified) / len(decided) if decided else None

    # How long the human took — i.e. how long a caller would have been holding.
    waits: list[float] = []
    for a in decided:
        created, done = _parse(a.get("created_at")), _parse(a.get("decided_at"))
        if created and done and done >= created:
            waits.append((done - created).total_seconds())

    tool_ms = [float(a["latency_ms"]) for a in executed if a.get("latency_ms") is not None]

    return {
        "actions": {
            "auto_executed": auto,
            "executed_after_approval": by_human,
            "declined_by_human": declined,
            "reversed": reversed_,
        },
        "autonomy_rate": round(autonomy, 3) if autonomy is not None else None,
        "override_rate": round(override, 3) if override is not None else None,
        "approvals": {
            "pending": len(pending),
            "decided": len(decided),
            "rejected": rejected,
            "modified": modified,
        },
        "time_to_decision_s": {
            "p50": _pct(waits, 0.50),
            "p95": _pct(waits, 0.95),
            "max": round(max(waits), 2) if waits else None,
        },
        "tool_latency_ms": {"p50": _pct(tool_ms, 0.50), "p95": _pct(tool_ms, 0.95)},
    }
