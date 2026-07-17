"""Seed the business tables with demo products, customers, and orders.

Order #4471 ($180, delivered 3 days ago, "damaged") is the canonical
damaged-refund walkthrough from docs/DESIGN.md. Idempotent: skips if data exists.

    PYTHONPATH=src python scripts/seed.py
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.db.models import Customer, Order, Product
from app.db.session import db_available, session_scope


async def main() -> None:
    if not db_available():
        raise SystemExit("DATABASE_URL is not set — nothing to seed.")

    async with session_scope() as s:
        catalog = [
            ("CERAMIC-DINNER-SET", "Ceramic dinner set", "180.00", "🍽️"),
            ("BLUETOOTH-SPEAKER", "Bluetooth speaker", "39.99", "🔊"),
            ("STANDING-DESK", "Standing desk", "640.00", "🪑"),
        ]
        products: dict[str, Product] = {}
        for sku, name, price, emoji in catalog:
            product = (await s.scalars(select(Product).where(Product.sku == sku))).first()
            if product is None:
                product = Product(
                    sku=sku, name=name, price=Decimal(price), emoji=emoji,
                )
                s.add(product)
                await s.flush()
            products[sku] = product

        existing = await s.scalar(select(func.count()).select_from(Customer))
        if existing:
            product_by_order = {
                4471: products["CERAMIC-DINNER-SET"].id,
                4472: products["BLUETOOTH-SPEAKER"].id,
                4473: products["STANDING-DESK"].id,
            }
            for order_id, product_id in product_by_order.items():
                order = await s.get(Order, order_id)
                if order is not None:
                    order.product_id = product_id
                    order.payment_ref = f"mock_pi_{order_id}"
            print(f"seed: catalog ready; {existing} customers already present; linked demo orders.")
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
                    product_id=products["CERAMIC-DINNER-SET"].id,
                    amount=Decimal("180.00"),
                    status="delivered",
                    item_description="Ceramic dinner set",
                    shipping_address="12 Oak St, Portland OR",
                    payment_ref="mock_pi_4471",
                    delivered_at=now - timedelta(days=3),
                ),
                Order(
                    id=4472,
                    customer_id=bob.id,
                    product_id=products["BLUETOOTH-SPEAKER"].id,
                    amount=Decimal("39.99"),
                    status="delivered",
                    item_description="Bluetooth speaker",
                    shipping_address="5 Pine Ave, Austin TX",
                    payment_ref="mock_pi_4472",
                    delivered_at=now - timedelta(days=10),
                ),
                Order(
                    id=4473,
                    customer_id=alice.id,
                    product_id=products["STANDING-DESK"].id,
                    amount=Decimal("640.00"),
                    status="in_transit",
                    item_description="Standing desk",
                    shipping_address="12 Oak St, Portland OR",
                    payment_ref="mock_pi_4473",
                ),
            ]
        )
    print("seed: 3 products, 2 customers, 3 orders inserted (incl. #4471 — $180 demo).")


if __name__ == "__main__":
    asyncio.run(main())
