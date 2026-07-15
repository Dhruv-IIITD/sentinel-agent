"""PII redaction guardrail."""

from __future__ import annotations

from app.domain.ecommerce import MemoryStore
from app.safety.guardrails import redact


def test_redacts_email_and_card_but_keeps_numbers():
    out = redact({
        "email": "alice@example.com",
        "card": "4111 1111 1111 1111",
        "order_id": 4471,
        "amount": 180.0,
    })
    assert out["email"] == "[redacted-email]"
    assert "[redacted-card]" in out["card"]
    assert out["order_id"] == 4471  # ids/amounts untouched
    assert out["amount"] == 180.0


def test_redacts_nested_structures():
    out = redact({"notes": ["reach me at bob@example.com", "ok"], "n": 5})
    assert "[redacted-email]" in out["notes"][0]
    assert out["notes"][1] == "ok"
    assert out["n"] == 5


async def test_audit_write_redacts_pii():
    store = MemoryStore()
    await store.write_audit(
        thread_id="t", event_type="executed", actor="agent", tool_name="add_note",
        args={"note": "customer email alice@example.com"},
        result={"customer_email": "bob@example.com"},
    )
    entry = store.audit[-1]
    assert "[redacted-email]" in entry["args"]["note"]
    assert entry["result"]["customer_email"] == "[redacted-email]"
