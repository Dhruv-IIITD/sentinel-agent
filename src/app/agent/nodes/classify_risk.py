"""Classify each requested tool call into a risk tier and an approval decision.

- Read / reversible → auto-execute.
- High-stakes → always approval.
- Dynamic (`issue_refund`) → the **policy engine decides at runtime** from the
  refund amount and the delivery window, and the retrieved policy clause becomes
  the justification shown to the approver.
- Hard cap → a refund above `hard_cap` is always gated, regardless of policy.

When `store`/`policy` aren't injected (e.g. a unit test of the classifier in
isolation), the dynamic tier falls back to requiring approval.
"""

from __future__ import annotations

from ...constants import RiskTier
from ...tools.registry import REGISTRY
from ..state import AgentState


async def _decide(spec, args: dict, store, policy, hard_cap) -> tuple[bool, str]:
    tier = spec.tier
    if tier in (RiskTier.READ, RiskTier.REVERSIBLE):
        return False, f"{tier.value} tier — auto-executed"
    if tier == RiskTier.HIGH_STAKES:
        return True, f"{tier.value} tier — requires human approval"
    if tier == RiskTier.DYNAMIC:
        amount = float(args.get("amount", 0) or 0)
        if hard_cap is not None and amount > hard_cap:
            return True, f"${amount:.2f} exceeds the ${hard_cap:.0f} hard cap — director approval required"
        if policy is None or store is None:
            return True, "dynamic tier — approval required (policy engine unavailable)"
        order = await store.get_order(int(args.get("order_id", 0) or 0))
        delivered = order.get("delivered_at") if isinstance(order, dict) else None
        decision = policy.decide_refund(amount, delivered)
        reason = decision.reason
        if decision.citation:
            reason = f"{reason} [policy: {decision.citation}]"
        return decision.needs_approval, reason
    return True, "unknown tier — approval required"


def make_classify_risk(store=None, policy=None, hard_cap=None, confidence_threshold=0.0):
    async def classify_risk(state: AgentState) -> dict:
        messages = state.get("messages") or []
        last = messages[-1] if messages else None
        confidence = float(state.get("confidence", 1.0))
        low_confidence = confidence < confidence_threshold

        plans = []
        for tc in getattr(last, "tool_calls", None) or []:
            spec = REGISTRY.get(tc["name"])
            if spec is None:
                plans.append({
                    "id": tc["id"], "name": tc["name"], "args": tc.get("args", {}),
                    "tier": "unknown", "needs_approval": True, "reason": "unknown tool",
                })
                continue
            needs, reason = await _decide(spec, tc.get("args", {}), store, policy, hard_cap)
            # Confidence-based escalation: gate even an auto action when the agent is unsure.
            if low_confidence and not needs:
                needs = True
                reason = (
                    f"escalated — agent confidence {confidence:.2f} below "
                    f"{confidence_threshold:.2f}; {reason}"
                )
            plans.append({
                "id": tc["id"], "name": tc["name"], "args": tc.get("args", {}),
                "tier": spec.tier.value, "needs_approval": needs, "reason": reason,
            })
        return {"plans": plans}

    return classify_risk
