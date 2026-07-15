"""High-stakes / dynamic executors — gated by approval, exactly-once on execute.

`issue_refund` is the *dynamic* tier: in Phase 1 it defaults to requiring
approval; in Phase 2 the policy-RAG classifier decides at runtime based on the
amount and the delivery window.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..domain.ecommerce import ExecCtx, Store


async def issue_refund(args: dict, store: "Store", ctx: "ExecCtx | None" = None) -> dict:
    return await store.issue_refund(
        int(args["order_id"]), float(args["amount"]), str(args.get("reason", "")), ctx
    )


async def cancel_order(args: dict, store: "Store", ctx: "ExecCtx | None" = None) -> dict:
    return await store.cancel_order(int(args["order_id"]), str(args.get("reason", "")), ctx)


async def apply_credit(args: dict, store: "Store", ctx: "ExecCtx | None" = None) -> dict:
    return await store.apply_credit(
        int(args["customer_id"]), float(args["amount"]), str(args.get("reason", "")), ctx
    )
