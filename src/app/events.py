"""Pluggable broadcast bus for observational application events.

Redis carries events across API workers when configured. The in-process bus is
the zero-infrastructure default for local development and tests. Event delivery
must never become part of approval correctness, so callers publish through
``safe_publish`` and treat failures as debug-only telemetry loss.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

APPROVAL_CHANNEL = "hitl:approval-events"


@runtime_checkable
class EventBus(Protocol):
    async def publish(self, event: dict) -> None: ...
    def subscribe(self) -> AsyncIterator[dict]: ...


class InProcessEventBus:
    """Broadcast each event to every subscriber in this process."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict]] = set()

    async def publish(self, event: dict) -> None:
        for queue in tuple(self._subscribers):
            queue.put_nowait(dict(event))

    async def subscribe(self) -> AsyncIterator[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)


class RedisEventBus:
    """Redis Pub/Sub broadcast shared by every API worker."""

    def __init__(self, redis_url: str, channel: str = APPROVAL_CHANNEL) -> None:
        from redis.asyncio import Redis

        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self.channel = channel

    async def publish(self, event: dict) -> None:
        await self._redis.publish(self.channel, json.dumps(event))

    async def subscribe(self) -> AsyncIterator[dict]:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self.channel)
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                payload = json.loads(message["data"])
                if isinstance(payload, dict):
                    yield payload
        finally:
            await pubsub.unsubscribe(self.channel)
            await pubsub.aclose()

    async def aclose(self) -> None:
        await self._redis.aclose()


async def safe_publish(bus: EventBus, event: dict) -> None:
    """Publish observationally: a bus outage cannot break the action flow."""
    try:
        await bus.publish(event)
    except Exception as exc:  # noqa: BLE001 - telemetry must never break approvals
        logger.debug("event publish failed: %s", exc)


def build_event_bus(settings) -> EventBus:
    if settings.redis_configured:
        return RedisEventBus(settings.redis_url)
    return InProcessEventBus()
