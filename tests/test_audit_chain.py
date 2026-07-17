"""The audit ledger exposes edits by chaining every stored entry."""

from __future__ import annotations

from app.domain.ecommerce import MemoryStore
from app.safety.audit_chain import canonical, chain_hash


async def _store_with_audit() -> MemoryStore:
    store = MemoryStore()
    await store.write_audit(
        thread_id="audit-thread",
        event_type="planned",
        actor="agent",
        tool_name="get_order",
        args={"order_id": 4471},
    )
    await store.write_audit(
        thread_id="audit-thread",
        event_type="executed",
        actor="agent",
        tool_name="get_order",
        args={"order_id": 4471},
        result={"status": "delivered"},
    )
    await store.write_audit(
        thread_id="audit-thread",
        event_type="reviewed",
        actor="human",
        result={"outcome": "accepted"},
    )
    return store


async def test_written_entries_form_an_intact_chain():
    store = await _store_with_audit()

    assert await store.verify_audit_chain() == {
        "intact": True,
        "entries": 3,
        "broken_at": None,
    }
    assert store.audit[0]["prev_hash"] is None
    assert store.audit[1]["prev_hash"] == store.audit[0]["entry_hash"]
    assert store.audit[2]["prev_hash"] == store.audit[1]["entry_hash"]
    assert store.audit[1]["entry_hash"] == chain_hash(
        store.audit[0]["entry_hash"], store.audit[1]
    )


async def test_tampering_reports_the_first_changed_entry():
    store = await _store_with_audit()
    store.audit[1]["result"]["status"] = "cancelled"

    assert await store.verify_audit_chain() == {
        "intact": False,
        "entries": 3,
        "broken_at": 1,
    }


async def test_untampered_chain_reverifies_and_hash_fields_are_excluded():
    store = await _store_with_audit()
    before = canonical(store.audit[0])
    store.audit[0]["entry_hash"] = "temporarily changed"
    store.audit[0]["prev_hash"] = "also ignored by canonical form"

    assert canonical(store.audit[0]) == before

    store = await _store_with_audit()
    first = await store.verify_audit_chain()
    second = await store.verify_audit_chain()
    assert first == second == {"intact": True, "entries": 3, "broken_at": None}
