"""Caller verification remains scoped to both the call and the order."""

from __future__ import annotations

from app.config import Settings
from app.safety.verification import (
    InMemoryVerificationStore,
    build_verification_store,
)


async def test_in_memory_verification_isolated_by_thread_and_order():
    verification = InMemoryVerificationStore()

    assert await verification.is_verified("call-a", 4471) is False
    await verification.mark("call-a", 4471)

    assert await verification.is_verified("call-a", 4471) is True
    assert await verification.is_verified("call-a", 4472) is False
    assert await verification.is_verified("call-b", 4471) is False


def test_verification_factory_defaults_to_memory_without_redis():
    store = build_verification_store(Settings(redis_url=""))
    assert isinstance(store, InMemoryVerificationStore)
