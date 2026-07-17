"""The approval event bus broadcasts without becoming a correctness dependency."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.ws import router as ws_router
from app.events import InProcessEventBus


async def test_in_process_bus_broadcasts_to_every_subscriber():
    bus = InProcessEventBus()
    first = bus.subscribe()
    second = bus.subscribe()
    first_event = asyncio.create_task(anext(first))
    second_event = asyncio.create_task(anext(second))
    await asyncio.sleep(0)  # enter both generators and register their queues

    event = {"type": "approval.created", "approval_id": "a1"}
    await bus.publish(event)

    assert await first_event == event
    assert await second_event == event
    await first.aclose()
    await second.aclose()


async def test_raising_subscriber_does_not_break_publish():
    bus = InProcessEventBus()

    async def broken_subscriber() -> None:
        async for _event in bus.subscribe():
            raise RuntimeError("consumer failed")

    consumer = asyncio.create_task(broken_subscriber())
    await asyncio.sleep(0)
    await bus.publish({"type": "first"})
    with pytest.raises(RuntimeError, match="consumer failed"):
        await consumer

    # Delivery is queue-based; a failed consumer cannot make later publishing fail.
    await bus.publish({"type": "second"})


def test_approval_websocket_connects_and_closes_cleanly():
    app = FastAPI()
    app.state.event_bus = InProcessEventBus()
    app.include_router(ws_router)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/approvals"):
            pass
