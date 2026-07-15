"""The tool registry — the single source of truth mapping each tool to its
risk tier, argument schema, and executor.

`classify_risk` reads the tier from here; `execute_tools` dispatches to the
executor; the model is bound with `langchain_tools()` so it can only call
registered tools (an implicit whitelist).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from ..constants import RiskTier
from . import highstakes, read, reversible, schemas

# Executor signature: (validated_args, store, ctx | None) -> result dict
Executor = Callable[..., Awaitable[dict]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    tier: RiskTier
    args_schema: type[BaseModel]
    executor: Executor


REGISTRY: dict[str, ToolSpec] = {}


def _register(spec: ToolSpec) -> None:
    REGISTRY[spec.name] = spec


# --- Read (auto) ---
_register(ToolSpec(
    "get_order",
    "Look up an order by its number: amount, status, item, delivery date, and customer.",
    RiskTier.READ, schemas.GetOrderArgs, read.get_order,
))
_register(ToolSpec(
    "check_inventory",
    "Check current stock for a product SKU.",
    RiskTier.READ, schemas.CheckInventoryArgs, read.check_inventory,
))
_register(ToolSpec(
    "track_shipment",
    "Get the current shipment/tracking status for an order.",
    RiskTier.READ, schemas.TrackShipmentArgs, read.track_shipment,
))

# --- Reversible write (auto + logged) ---
_register(ToolSpec(
    "update_address",
    "Update the shipping address on an order. Reversible.",
    RiskTier.REVERSIBLE, schemas.UpdateAddressArgs, reversible.update_address,
))
_register(ToolSpec(
    "add_note",
    "Attach an internal note to an order. Reversible.",
    RiskTier.REVERSIBLE, schemas.AddNoteArgs, reversible.add_note,
))

# --- High-stakes (always approval) ---
_register(ToolSpec(
    "cancel_order",
    "Cancel an order. High-stakes: requires human approval.",
    RiskTier.HIGH_STAKES, schemas.CancelOrderArgs, highstakes.cancel_order,
))
_register(ToolSpec(
    "apply_credit",
    "Apply store credit to a customer's account. High-stakes: requires approval.",
    RiskTier.HIGH_STAKES, schemas.ApplyCreditArgs, highstakes.apply_credit,
))

# --- Dynamic (approval decided at runtime by policy RAG in Phase 2) ---
_register(ToolSpec(
    "issue_refund",
    "Issue a refund against an order. Whether this needs approval depends on the "
    "refund policy (amount and delivery window).",
    RiskTier.DYNAMIC, schemas.IssueRefundArgs, highstakes.issue_refund,
))


def _never(*_args, **_kwargs):  # pragma: no cover - defensive
    raise RuntimeError("Tools are executed by the execute_tools node, not directly.")


def langchain_tools() -> list[StructuredTool]:
    """Tool definitions for `model.bind_tools(...)`.

    Only the name/description/args_schema are used for binding — execution is
    always routed through the execute_tools node, so the func is a guard.
    """
    return [
        StructuredTool(
            name=spec.name,
            description=spec.description,
            args_schema=spec.args_schema,
            func=_never,
        )
        for spec in REGISTRY.values()
    ]
