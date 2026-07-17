"""Approval SLA escalation, isolated from its background scheduler.

V1 only flags and notifies. An opt-in auto-reject policy may be added as a
future follow-up, but graph decisions do not belong in this sweep today.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .events import EventBus, safe_publish


def _timestamp(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


async def sweep(store, event_bus: EventBus, sla_seconds: int, now: datetime) -> list[str]:
    """Flag and announce pending approvals that have exceeded their SLA."""
    if sla_seconds <= 0:
        return []

    now = _timestamp(now)
    escalated_ids: list[str] = []
    approvals = await store.list_approvals(status="pending")
    for approval in approvals:
        if approval.get("escalated_at") is not None or approval.get("created_at") is None:
            continue
        age_seconds = int((now - _timestamp(approval["created_at"])).total_seconds())
        if age_seconds < sla_seconds:
            continue

        escalated = await store.mark_escalated(approval["id"], at=now)
        if escalated is None:
            continue
        escalated_ids.append(approval["id"])
        await safe_publish(event_bus, {
            "type": "approval.escalated",
            "approval_id": approval["id"],
            "thread_id": approval["thread_id"],
            "age_seconds": age_seconds,
            "at": now.isoformat(),
        })

    return escalated_ids
