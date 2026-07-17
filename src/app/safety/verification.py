"""Pluggable caller-verification state.

The in-memory implementation preserves the zero-infrastructure development
path. Redis sets make the same per-thread, per-order identity gate correct when
requests from one call can land on different API workers.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class VerificationStore(Protocol):
    async def mark(self, thread_id: str, order_id: int) -> None: ...
    async def is_verified(self, thread_id: str, order_id: int) -> bool: ...


class InMemoryVerificationStore:
    def __init__(self) -> None:
        self._verified: dict[str, set[int]] = {}

    async def mark(self, thread_id: str, order_id: int) -> None:
        self._verified.setdefault(thread_id, set()).add(order_id)

    async def is_verified(self, thread_id: str, order_id: int) -> bool:
        return order_id in self._verified.get(thread_id, set())


class RedisVerificationStore:
    def __init__(self, redis_url: str, ttl_seconds: int = 30 * 60) -> None:
        from redis.asyncio import Redis

        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _key(thread_id: str) -> str:
        return f"hitl:verified-orders:{thread_id}"

    async def mark(self, thread_id: str, order_id: int) -> None:
        key = self._key(thread_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.sadd(key, order_id)
            pipe.expire(key, self.ttl_seconds)
            await pipe.execute()

    async def is_verified(self, thread_id: str, order_id: int) -> bool:
        return bool(await self._redis.sismember(self._key(thread_id), order_id))

    async def aclose(self) -> None:
        await self._redis.aclose()


def build_verification_store(settings) -> VerificationStore:
    if settings.redis_configured:
        return RedisVerificationStore(settings.redis_url, settings.verification_ttl_seconds)
    return InMemoryVerificationStore()
