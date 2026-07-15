"""The store-data surface: seeing customers/orders, and creating your own so you can
call in and verify against a real record. This is what turns the engine from an
invisible fixture into something an operator can actually use.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.domain.ecommerce import MemoryStore
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
