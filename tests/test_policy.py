"""Policy-RAG driven routing: retrieved policy decides whether a refund is gated."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from langchain_core.messages import AIMessage

from app.agent.nodes.classify_risk import make_classify_risk
from app.domain.ecommerce import MemoryStore
from app.rag.policy import build_policy_engine


def _recent(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# --- Policy engine in isolation ---

def test_small_recent_refund_is_auto_approved():
    d = build_policy_engine().decide_refund(30.0, _recent(3))
    assert d.needs_approval is False
    assert d.citation  # a specific clause was retrieved and cited


def test_large_refund_gated_by_amount():
    d = build_policy_engine().decide_refund(180.0, _recent(3))
    assert d.needs_approval is True
    assert "50" in d.reason


def test_old_refund_gated_by_window():
    d = build_policy_engine().decide_refund(20.0, _recent(45))
    assert d.needs_approval is True
    assert "window" in d.reason.lower()


def test_editing_policy_changes_routing(tmp_path):
    # Raising the auto-approve limit to $200 flips the $180 decision — no code change.
    (tmp_path / "refund.md").write_text(
        "## Refunds\n"
        "- Refunds of $200.00 or less may be issued automatically.\n"
        "- Refunds greater than $200.00 require manager approval.\n"
        "- Refunds are only permitted within 30 days of delivery.\n"
    )
    d = build_policy_engine(tmp_path).decide_refund(180.0, _recent(3))
    assert d.needs_approval is False


# --- Policy wired into the classifier node ---

async def _classify(store, policy, hard_cap, name, args):
    node = make_classify_risk(store=store, policy=policy, hard_cap=hard_cap)
    ai = AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "tc"}])
    out = await node({"messages": [ai], "plans": [], "decisions": {}, "user_id": "u"})
    return out["plans"][0]


async def test_classifier_auto_approves_small_refund_via_policy():
    plan = await _classify(MemoryStore(), build_policy_engine(), 1000.0,
                           "issue_refund", {"order_id": 4472, "amount": 30.0})
    assert plan["needs_approval"] is False
    assert "policy" in plan["reason"].lower()


async def test_classifier_gates_large_refund_via_policy():
    plan = await _classify(MemoryStore(), build_policy_engine(), 1000.0,
                           "issue_refund", {"order_id": 4471, "amount": 180.0})
    assert plan["needs_approval"] is True


async def test_hard_cap_overrides_lenient_policy(tmp_path):
    (tmp_path / "p.md").write_text(
        "## Refunds\n- Refunds of $5000.00 or less may be issued automatically.\n"
        "- Refunds are only permitted within 30 days of delivery.\n"
    )
    plan = await _classify(MemoryStore(), build_policy_engine(tmp_path), 1000.0,
                           "issue_refund", {"order_id": 4471, "amount": 2000.0})
    assert plan["needs_approval"] is True
    assert "hard cap" in plan["reason"].lower()
