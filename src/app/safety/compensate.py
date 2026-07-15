"""Compensating-action registry — which side effects can be rolled back.

The actual inverse operations live in the Store (they touch business state and
the ledger atomically); this module just declares what is compensable, so the
API/UI can offer a rollback and reject non-compensable requests early.
"""

from __future__ import annotations

COMPENSABLE: set[str] = {"issue_refund", "cancel_order", "apply_credit"}

INVERSE: dict[str, str] = {
    "issue_refund": "reverse_refund",
    "cancel_order": "reinstate_order",
    "apply_credit": "reverse_credit",
}


def is_compensable(tool_name: str) -> bool:
    return tool_name in COMPENSABLE
