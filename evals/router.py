"""Run the real routing classifier over an eval case.

Uses the actual `classify_risk._decide` path with the policy engine and hard cap,
so the eval measures the shipped router — not a re-implementation of it.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make `app` importable when run as a standalone script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.agent.nodes.classify_risk import _decide  # noqa: E402
from app.config import settings  # noqa: E402
from app.rag.policy import build_policy_engine  # noqa: E402
from app.tools.registry import REGISTRY  # noqa: E402


class CaseStore:
    """Minimal store returning an order with a synthesized delivery date."""

    def __init__(self, delivered_days_ago: int | None) -> None:
        self.days = delivered_days_ago

    async def get_order(self, order_id: int) -> dict:
        if self.days is None:
            return {"delivered_at": None}
        iso = (datetime.now(timezone.utc) - timedelta(days=self.days)).isoformat()
        return {"delivered_at": iso}


_POLICY = None


def _policy():
    global _POLICY
    if _POLICY is None:
        _POLICY = build_policy_engine()
    return _POLICY


async def predict(case: dict, hard_cap: float | None = None) -> tuple[bool, str]:
    spec = REGISTRY[case["tool"]]
    args = {
        "order_id": 1, "customer_id": 1, "amount": case.get("amount") or 0,
        "new_address": "x", "note": "n", "sku": "SKU", "reason": "",
    }
    store = CaseStore(case.get("delivered_days_ago"))
    cap = settings.hard_refund_cap if hard_cap is None else hard_cap
    return await _decide(spec, args, store, _policy(), cap)
