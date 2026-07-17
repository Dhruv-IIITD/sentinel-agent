"""WebSocket feed for real-time approval lifecycle events."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


@router.websocket("/ws/approvals")
async def approval_events(websocket: WebSocket) -> None:
    await websocket.accept()
    subscription = websocket.app.state.event_bus.subscribe()
    event_task = asyncio.create_task(anext(subscription))
    receive_task = asyncio.create_task(websocket.receive())
    try:
        while True:
            done, _ = await asyncio.wait(
                {event_task, receive_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if receive_task in done:
                message = receive_task.result()
                if message["type"] == "websocket.disconnect":
                    break
                receive_task = asyncio.create_task(websocket.receive())

            if event_task in done:
                try:
                    event = event_task.result()
                except StopAsyncIteration:
                    break
                await websocket.send_json(event)
                event_task = asyncio.create_task(anext(subscription))
    except Exception as exc:  # noqa: BLE001 - disconnect variants differ by server
        logger.debug("approval WebSocket closed: %s", exc)
    finally:
        event_task.cancel()
        receive_task.cancel()
        await asyncio.gather(event_task, receive_task, return_exceptions=True)
        await subscription.aclose()
