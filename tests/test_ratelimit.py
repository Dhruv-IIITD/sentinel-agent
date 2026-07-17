"""Rate limiting is pluggable, disabled by default, and fail-open."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.ecommerce import MemoryStore
from app.main import app
from app.safety.ratelimit import (
    InMemoryRateLimiter,
    NoOpRateLimiter,
    build_rate_limiter,
)


async def test_in_memory_limiter_blocks_after_limit_and_returns_retry_after():
    limiter = InMemoryRateLimiter(limit=3)

    for _ in range(3):
        assert await limiter.allow("caller") == (True, 0)

    allowed, retry_after = await limiter.allow("caller")
    assert allowed is False
    assert retry_after > 0


def test_app_returns_429_after_client_limit():
    with TestClient(app) as client:
        app.state.store = MemoryStore()
        app.state.rate_limiter = InMemoryRateLimiter(limit=3)

        for _ in range(3):
            assert client.get("/store/products").status_code == 200

        blocked = client.get("/store/products")
        assert blocked.status_code == 429
        assert blocked.json() == {"detail": "rate limit exceeded"}
        assert int(blocked.headers["Retry-After"]) > 0


def test_default_limiter_never_blocks_requests():
    limiter = build_rate_limiter(Settings(redis_url="", rate_limit_per_minute=0))
    assert isinstance(limiter, NoOpRateLimiter)

    with TestClient(app) as client:
        app.state.store = MemoryStore()
        app.state.rate_limiter = limiter
        for _ in range(10):
            assert client.get("/store/products").status_code == 200


def test_health_check_bypasses_limiter():
    with TestClient(app) as client:
        app.state.rate_limiter = InMemoryRateLimiter(limit=1)
        for _ in range(4):
            assert client.get("/healthz").status_code == 200


def test_limiter_errors_fail_open():
    class BrokenLimiter:
        async def allow(self, key: str) -> tuple[bool, int]:
            raise RuntimeError("limiter unavailable")

    with TestClient(app) as client:
        app.state.store = MemoryStore()
        app.state.rate_limiter = BrokenLimiter()
        assert client.get("/store/products").status_code == 200
