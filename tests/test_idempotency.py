"""Exactly-once semantics of the idempotency ledger (MemoryStore reference impl)."""

from __future__ import annotations

from app.domain.ecommerce import ExecCtx, MemoryStore
from app.safety.idempotency import idempotency_key


async def test_same_key_refund_is_exactly_once():
    store = MemoryStore()
    ctx = ExecCtx(thread_id="t", idempotency_key="k1")

    r1 = await store.issue_refund(4471, 180.0, "damaged", ctx)
    r2 = await store.issue_refund(4471, 180.0, "damaged", ctx)  # replay, same key

    assert store.refund_count() == 1
    assert r1["refund_id"] == r2["refund_id"]
    assert r2.get("idempotent_replay") is True


async def test_different_keys_execute_independently():
    store = MemoryStore()
    a = await store.issue_refund(4471, 10.0, "x", ExecCtx("t", "ka"))
    b = await store.issue_refund(4471, 10.0, "x", ExecCtx("t", "kb"))

    assert store.refund_count() == 2
    assert a["refund_id"] != b["refund_id"]


async def test_no_ctx_means_no_dedupe():
    store = MemoryStore()
    await store.issue_refund(4471, 10.0, "x", None)
    await store.issue_refund(4471, 10.0, "x", None)
    assert store.refund_count() == 2


def test_key_is_stable_and_call_scoped():
    assert idempotency_key("t1", "tc_a") == idempotency_key("t1", "tc_a")
    assert idempotency_key("t1", "tc_a") != idempotency_key("t1", "tc_b")
    assert idempotency_key("t1", "tc_a") != idempotency_key("t2", "tc_a")
