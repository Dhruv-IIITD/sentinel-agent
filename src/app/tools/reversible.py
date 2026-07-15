"""Reversible-write executors — auto-executed + logged, still exactly-once.

Reversible writes don't require approval, but they *are* side effects, so they
still flow through the idempotency ledger via ``ctx`` (a resumed or retried turn
never double-applies them).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..domain.ecommerce import ExecCtx, Store


async def update_address(args: dict, store: "Store", ctx: "ExecCtx | None" = None) -> dict:
    return await store.update_address(int(args["order_id"]), str(args["new_address"]), ctx)


async def add_note(args: dict, store: "Store", ctx: "ExecCtx | None" = None) -> dict:
    return await store.add_note(int(args["order_id"]), str(args["note"]), "agent", ctx)
