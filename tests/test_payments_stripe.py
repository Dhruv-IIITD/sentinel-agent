"""Stripe adapter tests use an injected async client: no key, network, or threads."""

from __future__ import annotations

from types import SimpleNamespace

import stripe

from app.config import Settings
from app.domain.ecommerce import ExecCtx, MemoryStore
from app.payments import MockPaymentProvider, StripePaymentProvider, build_payment_provider


class FakeAsyncService:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[dict | None, dict | None]] = []

    async def create_async(self, params=None, options=None):
        self.calls.append((params, options))
        if self.error is not None:
            raise self.error
        return self.response


class FakeStripeClient:
    def __init__(
        self,
        *,
        payment_intent=None,
        refund=None,
        refund_error: Exception | None = None,
    ) -> None:
        self.payment_intents = FakeAsyncService(payment_intent)
        self.refunds = FakeAsyncService(refund, refund_error)
        self.v1 = SimpleNamespace(
            payment_intents=self.payment_intents,
            refunds=self.refunds,
        )


async def test_create_payment_uses_confirmed_test_payment_intent():
    client = FakeStripeClient(
        payment_intent=SimpleNamespace(id="pi_test_123", status="succeeded")
    )
    provider = StripePaymentProvider("", client=client)

    result = await provider.create_payment(
        order_id=4472,
        amount=39.99,
        description="Bluetooth speaker",
    )

    assert result == {"payment_ref": "pi_test_123", "status": "succeeded"}
    assert client.payment_intents.calls == [(
        {
            "amount": 3999,
            "currency": "usd",
            "payment_method": "pm_card_visa",
            "payment_method_types": ["card"],
            "confirm": True,
            "description": "Bluetooth speaker",
            "metadata": {"order_id": "4472"},
        },
        None,
    )]


async def test_refund_forwards_our_idempotency_key_and_payment_intent():
    client = FakeStripeClient(
        refund=SimpleNamespace(id="re_test_123", status="succeeded")
    )
    provider = StripePaymentProvider("", client=client)

    result = await provider.refund(
        payment_ref="pi_order_payment",
        amount=12.34,
        idempotency_key="our-refund-key",
        reason="duplicate order",
    )

    assert result == {
        "provider": "stripe",
        "refund_id": "re_test_123",
        "status": "succeeded",
    }
    assert client.refunds.calls == [(
        {
            "payment_intent": "pi_order_payment",
            "amount": 1234,
            "reason": "duplicate",
            "metadata": {"reason": "duplicate order"},
        },
        {"idempotency_key": "our-refund-key"},
    )]


async def test_refund_maps_stripe_error_without_recording_success():
    client = FakeStripeClient(refund_error=stripe.StripeError("refund failed"))
    provider = StripePaymentProvider("", client=client)
    store = MemoryStore(payments=provider)
    ctx = ExecCtx(thread_id="thread-1", idempotency_key="failed-refund-key")

    result = await store.issue_refund(4471, 180.0, "damaged", ctx)

    assert result == {"error": "refund failed"}
    assert store.refunds == []
    assert "failed-refund-key" not in store.executions


async def test_stripe_compensation_is_internal_and_records_terminal_note():
    client = FakeStripeClient(
        refund=SimpleNamespace(id="re_test_456", status="succeeded")
    )
    store = MemoryStore(payments=StripePaymentProvider("", client=client))
    ctx = ExecCtx(thread_id="thread-2", idempotency_key="stripe-refund-key")

    await store.issue_refund(4471, 180.0, "damaged", ctx)
    undo = await store.compensate("stripe-refund-key")

    assert undo["note"] == (
        "Stripe refunds are terminal; no external re-charge was issued."
    )
    assert store.refunds[0]["status"] == "reversed"
    assert len(client.refunds.calls) == 1


def test_factory_keeps_mock_default_and_falls_back_without_key():
    assert isinstance(build_payment_provider(Settings()), MockPaymentProvider)
    assert isinstance(
        build_payment_provider(Settings(payments_provider="stripe", stripe_api_key="")),
        MockPaymentProvider,
    )


def test_factory_selects_stripe_when_explicitly_configured():
    provider = build_payment_provider(
        Settings(payments_provider="stripe", stripe_api_key="sk_test_fake")
    )

    assert isinstance(provider, StripePaymentProvider)
