"""Seed the business tables with demo customers and orders.

Order #4471 ($180, delivered 3 days ago, "damaged") is the canonical
damaged-refund walkthrough from docs/DESIGN.md. Idempotent: skips if data exists.

    PYTHONPATH=src python scripts/seed.py
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.db.models import Customer, Order
from app.db.session import db_available, session_scope


async def main() -> None:
    if not db_available():
        raise SystemExit("DATABASE_URL is not set — nothing to seed.")

    async with session_scope() as s:
        existing = await s.scalar(select(func.count()).select_from(Customer))
        if existing:
            print(f"seed: {existing} customers already present; skipping.")
            return

        now = datetime.now(timezone.utc)
        alice = Customer(name="Alice Rivera", email="alice@example.com")
        bob = Customer(name="Bob Chen", email="bob@example.com")
        s.add_all([alice, bob])
        await s.flush()  # assign customer ids

        s.add_all(
            [
                Order(
                    id=4471,
                    customer_id=alice.id,
                    amount=Decimal("180.00"),
                    status="delivered",
                    item_description="Ceramic dinner set (arrived damaged)",
                    shipping_address="12 Oak St, Portland OR",
                    delivered_at=now - timedelta(days=3),
                ),
                Order(
                    id=4472,
                    customer_id=bob.id,
                    amount=Decimal("39.99"),
                    status="delivered",
                    item_description="Bluetooth speaker",
                    shipping_address="5 Pine Ave, Austin TX",
                    delivered_at=now - timedelta(days=10),
                ),
                Order(
                    id=4473,
                    customer_id=alice.id,
                    amount=Decimal("640.00"),
                    status="in_transit",
                    item_description="Standing desk",
                    shipping_address="12 Oak St, Portland OR",
                ),
            ]
        )
    print("seed: 2 customers, 3 orders inserted (incl. #4471 — $180 damaged-refund demo).")


if __name__ == "__main__":
    asyncio.run(main())
