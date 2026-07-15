"""Static risk classification (Phase 1)."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from app.agent.nodes.classify_risk import make_classify_risk


async def test_static_tier_classification():
    node = make_classify_risk()
    ai = AIMessage(content="", tool_calls=[
        {"name": "get_order", "args": {"order_id": 4471}, "id": "a"},
        {"name": "update_address", "args": {"order_id": 4471, "new_address": "x"}, "id": "b"},
        {"name": "issue_refund", "args": {"order_id": 4471, "amount": 180}, "id": "c"},
        {"name": "cancel_order", "args": {"order_id": 4471}, "id": "d"},
    ])

    out = await node({"messages": [ai], "plans": [], "decisions": {}, "user_id": "u"})
    plans = {p["name"]: p for p in out["plans"]}

    assert plans["get_order"]["needs_approval"] is False
    assert plans["update_address"]["needs_approval"] is False
    assert plans["issue_refund"]["needs_approval"] is True
    assert plans["issue_refund"]["tier"] == "dynamic"
    assert plans["cancel_order"]["needs_approval"] is True
