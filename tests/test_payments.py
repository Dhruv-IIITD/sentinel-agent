"""Payment side effects stay pluggable and share the Store's idempotency key."""

from __future__ import annotations

from app.domain.ecommerce import ExecCtx, MemoryStore
from app.payments import MockPaymentProvider


class CountingPaymentProvider(MockPaymentProvider):
    def __init__(self) -> None:
        self.payment_calls: list[dict] = []
        self.refund_calls: list[dict] = []

    async def create_payment(
        self,
        *,
        order_id: int,
        amount: float,
        description: str = "",
    ) -> dict:
        self.payment_calls.append({
            "order_id": order_id,
            "amount": amount,
            "description": description,
        })
        return await super().create_payment(
            order_id=order_id, amount=amount, description=description
        )

    async def refund(
        self,
        *,
        payment_ref: str | None,
        amount: float,
        idempotency_key: str | None,
        reason: str = "",
    ) -> dict:
        self.refund_calls.append({
            "payment_ref": payment_ref,
            "amount": amount,
            "idempotency_key": idempotency_key,
            "reason": reason,
        })
        return await super().refund(
            payment_ref=payment_ref,
            amount=amount,
            idempotency_key=idempotency_key,
            reason=reason,
        )


async def test_mock_payment_provider_shapes():
    provider = MockPaymentProvider()

    assert await provider.create_payment(
        order_id=4471, amount=180.0, description="Ceramic dinner set"
    ) == {"payment_ref": "mock_pi_4471", "status": "succeeded"}
    assert await provider.refund(
        payment_ref="mock_pi_4471",
        amount=180.0,
        idempotency_key="refund-key",
        reason="damaged",
    ) == {
        "provider": "mock",
        "refund_id": "mock_re_refund-key",
        "status": "issued",
    }


async def test_store_refund_calls_provider_once_and_passes_idempotency_key():
    provider = CountingPaymentProvider()
    store = MemoryStore(payments=provider)
    ctx = ExecCtx(thread_id="thread-1", idempotency_key="refund-once")

    first = await store.issue_refund(4471, 180.0, "damaged", ctx)
    replay = await store.issue_refund(4471, 180.0, "damaged", ctx)

    assert len(provider.refund_calls) == 1
    assert provider.refund_calls[0] == {
        "payment_ref": "mock_pi_4471",
        "amount": 180.0,
        "idempotency_key": "refund-once",
        "reason": "damaged",
    }
    assert store.refund_count() == 1
    assert first["refund_id"] == replay["refund_id"] == 1
    assert first["status"] == "issued"
    assert first["provider"] == "mock"
    assert first["provider_refund_id"] == "mock_re_refund-once"
    assert replay["idempotent_replay"] is True
    assert store.refunds[0]["provider_refund_id"] == "mock_re_refund-once"


async def test_create_order_sets_payment_reference():
    provider = CountingPaymentProvider()
    store = MemoryStore(seed=False, payments=provider)
    customer = await store.create_customer("Buyer", "buyer@example.com")

    order = await store.create_order(customer["id"], "Desk lamp", 85.0)

    assert order["payment_ref"] == f"mock_pi_{order['id']}"
    assert provider.payment_calls == [{
        "order_id": order["id"],
        "amount": 85.0,
        "description": "Desk lamp",
    }]
