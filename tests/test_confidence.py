"""Confidence-based escalation: gate even auto actions when the agent is unsure."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.nodes.agent_node import make_agent_node
from app.agent.nodes.classify_risk import make_classify_risk
from app.domain.ecommerce import MemoryStore
from app.rag.policy import build_policy_engine
from tests.fakes import FakeModel


async def _classify_read_with_confidence(confidence: float) -> dict:
    node = make_classify_risk(
        store=MemoryStore(), policy=build_policy_engine(), hard_cap=1000.0, confidence_threshold=0.7
    )
    ai = AIMessage(content="", tool_calls=[{"name": "get_order", "args": {"order_id": 4471}, "id": "r"}])
    out = await node({"messages": [ai], "plans": [], "decisions": {}, "user_id": "u", "confidence": confidence})
    return out["plans"][0]


async def test_low_confidence_escalates_an_auto_action():
    plan = await _classify_read_with_confidence(0.3)
    assert plan["needs_approval"] is True
    assert "confidence" in plan["reason"].lower()


async def test_normal_confidence_does_not_escalate():
    plan = await _classify_read_with_confidence(1.0)
    assert plan["needs_approval"] is False


async def test_agent_node_surfaces_confidence():
    model = FakeModel([AIMessage(content="hi", additional_kwargs={"confidence": 0.4})])
    out = await make_agent_node(model)({"messages": [HumanMessage("x")]})
    assert out["confidence"] == 0.4
