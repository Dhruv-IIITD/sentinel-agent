"""Store data — see and create the products, customers, and orders the agent operates on.

The engine used to run on three invisible seeded orders, which is why a real caller
could never verify: there was nothing to see and nothing you could add. This exposes
the data (so an operator can read off the order number and email) and lets you create
an order — including *your own*, so you can call in and actually verify against it.

These are plain records, not agent actions: creating an order is not a side effect the
agent takes, so it does not go through the risk gate. The gate governs what the agent
does *to* an order (refund, cancel), not the existence of test data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, model_validator

from ..auth.deps import get_current_user

router = APIRouter(prefix="/store", tags=["store"])


@router.get("/customers")
async def list_customers(request: Request) -> list[dict]:
    return await request.app.state.store.list_customers()


@router.get("/orders")
async def list_orders(request: Request) -> list[dict]:
    return await request.app.state.store.list_orders()


@router.get("/customer-360/{order_id}", dependencies=[Depends(get_current_user)])
async def get_customer_360(order_id: int, request: Request) -> dict:
    return await request.app.state.store.get_customer_360(order_id)


@router.get("/products")
async def list_products(request: Request) -> list[dict]:
    return await request.app.state.store.list_products()


class NewProduct(BaseModel):
    sku: str = Field(min_length=1)
    name: str = Field(min_length=1)
    price: float = Field(gt=0)
    description: str = ""
    emoji: str = ""


@router.post("/products")
async def create_product(body: NewProduct, request: Request) -> dict:
    return await request.app.state.store.create_product(
        body.sku.strip(), body.name.strip(), float(body.price),
        body.description.strip(), body.emoji.strip(),
    )


class NewOrder(BaseModel):
    name: str = Field(min_length=1, description="Name on the order")
    email: str = Field(min_length=3, description="Email on the order — the verification anchor")
    product_id: int | None = Field(default=None, gt=0)
    item: str | None = Field(default=None, min_length=1)
    amount: float | None = Field(default=None, gt=0, description="Order total in USD")
    status: str = Field(default="delivered", description="delivered | in_transit | processing")
    delivered_days_ago: int | None = Field(
        default=2, description="How long ago it was delivered — drives the refund-window policy"
    )

    @model_validator(mode="after")
    def product_or_custom_item(self) -> "NewOrder":
        if self.product_id is None and (self.item is None or self.amount is None):
            raise ValueError("item and amount are required when product_id is not provided")
        return self


@router.post("/orders")
async def create_order(body: NewOrder, request: Request) -> dict:
    """Create an order (and its customer, by email, if new).

    Returns the order plus a `verify` hint: the exact order number and email to say on a
    call. Register yourself here, then start a voice call and verify against your own record.
    """
    store = request.app.state.store
    if body.product_id is not None and await store.get_product(body.product_id) is None:
        return {"error": f"product {body.product_id} not found"}
    customer = await store.create_customer(body.name.strip(), body.email.strip())

    delivered_at = None
    if body.status == "delivered" and body.delivered_days_ago is not None:
        delivered_at = (
            datetime.now(timezone.utc) - timedelta(days=body.delivered_days_ago)
        ).isoformat()

    order = await store.create_order(
        customer["id"], (body.item or "").strip(), float(body.amount or 0),
        body.status, delivered_at, product_id=body.product_id,
    )
    if "error" in order:
        return order
    return {
        "order": order,
        "customer": customer,
        "verify": {"order_id": order["id"], "email": customer["email"]},
    }
