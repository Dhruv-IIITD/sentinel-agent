"""Read-tier tool executors — no side effects, auto-executed, never gated.

Each executor takes ``(args, store, ctx)``; reads ignore ``ctx`` (no idempotency
ledger is needed for a read).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..domain.ecommerce import ExecCtx, Store


async def get_order(args: dict, store: "Store", ctx: "ExecCtx | None" = None) -> dict:
    return await store.get_order(int(args["order_id"]))


async def check_inventory(args: dict, store: "Store", ctx: "ExecCtx | None" = None) -> dict:
    return await store.check_inventory(str(args["sku"]))


async def track_shipment(args: dict, store: "Store", ctx: "ExecCtx | None" = None) -> dict:
    return await store.track_shipment(int(args["order_id"]))
