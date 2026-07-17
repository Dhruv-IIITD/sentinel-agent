"""Pluggable mock and Stripe payment side effects."""

from __future__ import annotations

import logging
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol, runtime_checkable

import stripe

logger = logging.getLogger(__name__)


@runtime_checkable
class PaymentProvider(Protocol):
    async def create_payment(
        self,
        *,
        order_id: int,
        amount: float,
        description: str = "",
    ) -> dict: ...

    async def refund(
        self,
        *,
        payment_ref: str | None,
        amount: float,
        idempotency_key: str | None,
        reason: str = "",
    ) -> dict: ...


class MockPaymentProvider:
    async def create_payment(
        self,
        *,
        order_id: int,
        amount: float,
        description: str = "",
    ) -> dict:
        return {"payment_ref": f"mock_pi_{order_id}", "status": "succeeded"}

    async def refund(
        self,
        *,
        payment_ref: str | None,
        amount: float,
        idempotency_key: str | None,
        reason: str = "",
    ) -> dict:
        anchor = idempotency_key or uuid.uuid4().hex
        return {"provider": "mock", "refund_id": f"mock_re_{anchor}", "status": "issued"}


def _cents(amount: float) -> int:
    return int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _field(resource, name: str):
    if isinstance(resource, dict):
        return resource.get(name)
    return getattr(resource, name, None)


def _stripe_reason(reason: str) -> str:
    normalized = reason.strip().lower().replace("-", "_").replace(" ", "_")
    if "duplicate" in normalized:
        return "duplicate"
    if "fraud" in normalized:
        return "fraudulent"
    return "requested_by_customer"


class StripePaymentProvider:
    """Stripe test-mode adapter using the SDK's native async service methods."""

    def __init__(self, api_key: str, client=None) -> None:
        self.client = client if client is not None else stripe.StripeClient(api_key)

    async def create_payment(
        self,
        *,
        order_id: int,
        amount: float,
        description: str = "",
    ) -> dict:
        try:
            payment_intent = await self.client.v1.payment_intents.create_async({
                "amount": _cents(amount),
                "currency": "usd",
                "payment_method": "pm_card_visa",
                "payment_method_types": ["card"],
                "confirm": True,
                "description": description,
                "metadata": {"order_id": str(order_id)},
            })
            return {
                "payment_ref": _field(payment_intent, "id"),
                "status": _field(payment_intent, "status"),
            }
        except stripe.StripeError as exc:
            return {"error": str(exc)}

    async def refund(
        self,
        *,
        payment_ref: str | None,
        amount: float,
        idempotency_key: str | None,
        reason: str = "",
    ) -> dict:
        try:
            refund = await self.client.v1.refunds.create_async(
                {
                    "payment_intent": payment_ref,
                    "amount": _cents(amount),
                    "reason": _stripe_reason(reason),
                    "metadata": {"reason": reason},
                },
                {"idempotency_key": idempotency_key},
            )
            return {
                "provider": "stripe",
                "refund_id": _field(refund, "id"),
                "status": _field(refund, "status"),
            }
        except stripe.StripeError as exc:
            return {"error": str(exc)}


def build_payment_provider(settings) -> PaymentProvider:
    """Select Stripe only when explicitly configured with an API key."""
    if settings.payments_provider.strip().lower() == "stripe":
        if settings.stripe_api_key:
            return StripePaymentProvider(settings.stripe_api_key)
        logger.warning("Stripe payments requested without STRIPE_API_KEY; using mock provider")
    return MockPaymentProvider()
