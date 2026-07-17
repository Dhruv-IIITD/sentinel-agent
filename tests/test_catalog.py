"""The store-data surface: seeing customers/orders, and creating your own so you can
call in and verify against a real record. This is what turns the engine from an
invisible fixture into something an operator can actually use.
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.domain.ecommerce import ExecCtx, MemoryStore
from app.main import app


def _client() -> TestClient:
    return TestClient(app)


def test_seed_data_is_visible():
    with _client() as client:
        app.state.store = MemoryStore()

        orders = client.get("/store/orders").json()
        assert {o["id"] for o in orders} == {4471, 4472, 4473}
        # the fields an operator needs to read off during a call
        first = next(o for o in orders if o["id"] == 4471)
        assert first["customer_name"] == "Alice Rivera"
        assert first["customer_email"] == "alice@example.com"
        assert first["amount"] == 180.0

        emails = {c["email"] for c in client.get("/store/customers").json()}
        assert "alice@example.com" in emails


def test_seed_products_are_visible():
    with _client() as client:
        app.state.store = MemoryStore()

        products = client.get("/store/products").json()
        assert [p["sku"] for p in products] == [
            "CERAMIC-DINNER-SET",
            "BLUETOOTH-SPEAKER",
            "STANDING-DESK",
        ]
        assert products[0]["price"] == 180.0
        assert products[0]["emoji"] == "🍽️"


def test_create_product_is_listed():
    with _client() as client:
        app.state.store = MemoryStore()

        resp = client.post(
            "/store/products",
            json={
                "sku": "MECH-KEYBOARD",
                "name": "Mechanical keyboard",
                "price": 140.0,
                "description": "Hot-swappable keyboard",
                "emoji": "⌨️",
            },
        )
        assert resp.status_code == 200, resp.text
        product = resp.json()
        assert product["id"] == 4
        assert product["active"] is True
        assert any(p["id"] == product["id"] for p in client.get("/store/products").json())


def test_create_order_from_product_uses_catalog_name_and_price():
    with _client() as client:
        app.state.store = MemoryStore()

        body = client.post(
            "/store/orders",
            json={
                "name": "Product Buyer",
                "email": "buyer@example.com",
                "product_id": 2,
                # Product selection wins over stale client-supplied values.
                "item": "Wrong item",
                "amount": 999.0,
            },
        ).json()

        assert body["order"]["product_id"] == 2
        assert body["order"]["item_description"] == "Bluetooth speaker"
        assert body["order"]["amount"] == 39.99


async def test_memory_store_rejects_unknown_product_for_order():
    store = MemoryStore()
    result = await store.create_order(
        1, "Ignored", 1.0, product_id=999,
    )
    assert result == {"error": "product 999 not found"}


def test_create_order_returns_a_verify_hint():
    with _client() as client:
        app.state.store = MemoryStore()

        resp = client.post(
            "/store/orders",
            json={"name": "Dhruv Sharma", "email": "dhruv@example.com",
                  "item": "Mechanical keyboard", "amount": 140.0},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        oid = body["order"]["id"]
        assert oid == 4474  # next after the seed
        # the whole point: exactly what to say on the call
        assert body["verify"] == {"order_id": oid, "email": "dhruv@example.com"}
        assert body["order"]["customer_name"] == "Dhruv Sharma"

        # and it is now visible + verifiable through the SAME gate the agent uses
        assert any(o["id"] == oid for o in client.get("/store/orders").json())
        v = client.post(
            "/voice/verify_identity",
            json={"thread_id": "t", "order_id": oid, "email_or_name": "dhruv@example.com"},
        ).json()
        assert v["verified"] is True


def test_creating_two_orders_for_one_email_reuses_the_customer():
    with _client() as client:
        app.state.store = MemoryStore()
        payload = {"name": "Sam", "email": "sam@example.com", "item": "x", "amount": 20.0}

        client.post("/store/orders", json=payload)
        client.post("/store/orders", json={**payload, "item": "y", "amount": 30.0})

        # email is the identity — one customer, two orders, not a duplicate
        sams = [c for c in client.get("/store/customers").json() if c["email"] == "sam@example.com"]
        assert len(sams) == 1
        sam_orders = [o for o in client.get("/store/orders").json() if o["customer_email"] == "sam@example.com"]
        assert len(sam_orders) == 2


def test_created_order_flows_through_the_real_refund_gate():
    """A refund on a user-created order is gated by policy exactly like a seeded one."""
    with _client() as client:
        app.state.store = MemoryStore()
        oid = client.post(
            "/store/orders",
            json={"name": "Pat", "email": "pat@example.com", "item": "Lamp",
                  "amount": 240.0, "delivered_days_ago": 1},
        ).json()["order"]["id"]

        client.post(
            "/voice/verify_identity",
            json={"thread_id": "c", "order_id": oid, "email_or_name": "pat@example.com"},
        )
        elig = client.get(f"/voice/refund_eligibility/{oid}", params={"thread_id": "c"}).json()
        assert elig["needs_approval"] is True  # $240 > $50 limit
        assert elig["amount"] == 240.0


def test_customer_360_contains_history_refunds_and_notes():
    store = MemoryStore()
    asyncio.run(store.issue_refund(
        4471,
        75.0,
        "damaged on arrival",
        ExecCtx(thread_id="customer-360", idempotency_key="customer-360-refund"),
    ))
    asyncio.run(store.add_note(
        4473,
        "Customer prefers email follow-up",
        "operator@demo",
        ExecCtx(thread_id="customer-360", idempotency_key="customer-360-note"),
    ))

    with _client() as client:
        app.state.store = store
        response = client.get("/store/customer-360/4471")

        assert response.status_code == 200, response.text
        bundle = response.json()
        assert bundle["customer"] == {
            "id": 1,
            "name": "Alice Rivera",
            "email": "alice@example.com",
        }
        assert {order["id"] for order in bundle["orders"]} == {4471, 4473}
        assert bundle["refunds"] == [{
            "order_id": 4471,
            "amount": 75.0,
            "status": "issued",
            "reason": "damaged on arrival",
            "provider": "mock",
        }]
        assert bundle["notes"] == [{
            "order_id": 4473,
            "note": "Customer prefers email follow-up",
            "author": "operator@demo",
        }]

        assert client.get("/store/customer-360/999999").json() == {
            "error": "order 999999 not found"
        }
