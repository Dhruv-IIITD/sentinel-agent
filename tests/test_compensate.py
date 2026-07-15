"""Compensation / rollback of executed side effects."""

from __future__ import annotations

from app.domain.ecommerce import ExecCtx, MemoryStore


async def test_compensate_reverses_refund_and_marks_ledger():
    store = MemoryStore()
    ctx = ExecCtx(thread_id="t", idempotency_key="k1")
    r = await store.issue_refund(4471, 180.0, "damaged", ctx)

    undo = await store.compensate("k1", actor="manager", reason="issued in error")

    assert undo["status"] == "compensated"
    assert undo["reversed_refund_id"] == r["refund_id"]
    assert store.refunds[0]["status"] == "reversed"
    assert store.executions["k1"]["compensated"] is True
    assert any(a["event_type"] == "compensated" for a in store.audit)


async def test_compensate_is_idempotent():
    store = MemoryStore()
    await store.issue_refund(4471, 50.0, "x", ExecCtx("t", "k2"))
    await store.compensate("k2")
    again = await store.compensate("k2")

    assert again["status"] == "already_compensated"
    assert sum(1 for a in store.audit if a["event_type"] == "compensated") == 1


async def test_compensate_unknown_key_errors():
    res = await MemoryStore().compensate("does-not-exist")
    assert "error" in res
