"""Pluggable, fail-open HTTP rate limiting.

The disabled and in-memory implementations keep local development free of
infrastructure. Redis supplies one shared counter per client across API workers.
Limiter failures are observational: requests continue rather than taking down
the customer-support API.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Protocol, runtime_checkable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger(__name__)


@runtime_checkable
class RateLimiter(Protocol):
    async def allow(self, key: str) -> tuple[bool, int]: ...


class NoOpRateLimiter:
    async def allow(self, key: str) -> tuple[bool, int]:
        return True, 0


class InMemoryRateLimiter:
    """A fixed-window limiter scoped to this process."""

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._windows: dict[str, tuple[float, int]] = {}

    async def allow(self, key: str) -> tuple[bool, int]:
        if self.limit <= 0:
            return True, 0

        now = time.monotonic()
        started_at, count = self._windows.get(key, (now, 0))
        elapsed = now - started_at
        if elapsed >= self.window_seconds:
            started_at, count, elapsed = now, 0, 0.0

        if count >= self.limit:
            return False, max(1, math.ceil(self.window_seconds - elapsed))

        self._windows[key] = (started_at, count + 1)
        return True, 0


class RedisRateLimiter:
    """A fixed-window Redis counter shared atomically across API workers."""

    _INCREMENT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return {count, redis.call('TTL', KEYS[1])}
"""

    def __init__(self, redis_url: str, limit: int, window_seconds: int = 60) -> None:
        from redis.asyncio import Redis

        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self.limit = limit
        self.window_seconds = window_seconds

    @staticmethod
    def _key(key: str) -> str:
        return f"hitl:rate-limit:{key}"

    async def allow(self, key: str) -> tuple[bool, int]:
        if self.limit <= 0:
            return True, 0
        try:
            count, ttl = await self._redis.eval(
                self._INCREMENT, 1, self._key(key), self.window_seconds
            )
            allowed = int(count) <= self.limit
            return allowed, 0 if allowed else max(1, int(ttl))
        except Exception as exc:  # noqa: BLE001 - limiter failures must fail open
            logger.warning("Redis rate limiter failed open: %s", exc)
            return True, 0

    async def aclose(self) -> None:
        try:
            await self._redis.aclose()
        except Exception as exc:  # noqa: BLE001 - limiter cleanup must not break shutdown
            logger.warning("Redis rate limiter cleanup failed: %s", exc)


def build_rate_limiter(settings) -> RateLimiter:
    limit = settings.rate_limit_per_minute
    if limit <= 0:
        return NoOpRateLimiter()
    if settings.redis_configured:
        try:
            return RedisRateLimiter(settings.redis_url, limit)
        except Exception as exc:  # noqa: BLE001 - construction also fails open
            logger.warning("Redis rate limiter unavailable; rate limiting disabled: %s", exc)
            return NoOpRateLimiter()
    return InMemoryRateLimiter(limit)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate-limit HTTP requests by the originating client IP."""

    @staticmethod
    def _skip(path: str) -> bool:
        return path == "/healthz" or path == "/ui" or path.startswith("/ui/")

    @staticmethod
    def _client_key(request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            first_hop = forwarded.split(",", 1)[0].strip()
            if first_hop:
                return first_hop
        return request.client.host if request.client is not None else "unknown"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if self._skip(request.url.path):
            return await call_next(request)

        limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
        if limiter is None:
            return await call_next(request)

        key = self._client_key(request)
        try:
            allowed, retry_after = await limiter.allow(key)
        except Exception as exc:  # noqa: BLE001 - injected/backends must fail open
            logger.warning("rate limiter failed open for %s: %s", key, exc)
            allowed, retry_after = True, 0

        if allowed:
            return await call_next(request)
        return JSONResponse(
            status_code=429,
            content={"detail": "rate limit exceeded"},
            headers={"Retry-After": str(max(1, retry_after))},
        )
