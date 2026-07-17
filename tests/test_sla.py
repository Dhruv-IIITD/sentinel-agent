"""Approval SLA sweeps are deterministic and idempotent."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.domain.ecommerce import MemoryStore
from app.events import InProcessEventBus
from app.sla import sweep


async def test_sweep_escalates_only_old_pending_approval_once():
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    store = MemoryStore(seed=False)
    old, fresh = await store.create_approvals(
        "call-1",
        "checkpoint-1",
        [
            {"tool_call_id": "old-call", "tool": "issue_refund", "args": {}},
            {"tool_call_id": "fresh-call", "tool": "cancel_order", "args": {}},
        ],
    )
    store.approvals[old["id"]]["created_at"] = (now - timedelta(seconds=90)).isoformat()
    store.approvals[fresh["id"]]["created_at"] = (now - timedelta(seconds=10)).isoformat()

    bus = InProcessEventBus()
    subscription = bus.subscribe()
    first_event = asyncio.create_task(anext(subscription))
    await asyncio.sleep(0)  # register the subscriber before the sweep publishes

    assert await sweep(store, bus, sla_seconds=60, now=now) == [old["id"]]
    escalated = await store.get_approval(old["id"])
    assert escalated["escalated_at"] == now.isoformat()
    assert escalated["status"] == "pending"  # v1 flags; it never decides or resumes the graph
    assert (await store.get_approval(fresh["id"]))["escalated_at"] is None
    assert await first_event == {
        "type": "approval.escalated",
        "approval_id": old["id"],
        "thread_id": "call-1",
        "age_seconds": 90,
        "at": now.isoformat(),
    }

    second_event = asyncio.create_task(anext(subscription))
    await asyncio.sleep(0)
    assert await sweep(store, bus, sla_seconds=60, now=now) == []
    await asyncio.sleep(0)
    assert second_event.done() is False
    second_event.cancel()
    await asyncio.gather(second_event, return_exceptions=True)
    await subscription.aclose()
