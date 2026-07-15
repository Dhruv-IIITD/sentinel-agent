"""The crown jewel: pause → persist → resume, and exactly-once across a restart."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.graph import build_graph
from app.domain.ecommerce import MemoryStore
from tests.fakes import FakeModel


def _refund_call(call_id: str = "tc_ref_1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{
            "name": "issue_refund",
            "args": {"order_id": 4471, "amount": 180.0, "reason": "damaged"},
            "id": call_id,
        }],
    )


def _init(text: str) -> dict:
    return {"messages": [HumanMessage(text)], "plans": [], "decisions": {}, "user_id": "u1"}


async def test_refund_pauses_persists_and_resumes_exactly_once():
    store = MemoryStore()
    checkpointer = MemorySaver()  # the shared "database" that survives the restart
    model = FakeModel([
        _refund_call(),
        AIMessage(content="Your $180 refund is processed — 3-5 business days."),
    ])
    cfg = {"configurable": {"thread_id": "t-refund"}}

    graph_1 = build_graph(checkpointer, store, model)
    paused = await graph_1.ainvoke(_init("My order 4471 arrived damaged, I want a refund."), cfg)

    # It paused at the approval node with a well-formed request, and nothing ran.
    assert "__interrupt__" in paused
    request = paused["__interrupt__"][0].value
    assert request[0]["tool"] == "issue_refund"
    assert request[0]["risk_tier"] == "dynamic"
    assert store.refund_count() == 0

    # --- Simulate a process restart: brand-new graph instance, SAME checkpointer + thread. ---
    graph_2 = build_graph(checkpointer, store, model)
    final = await graph_2.ainvoke(
        Command(resume={"tc_ref_1": {"decision": "approve", "decided_by": "manager"}}), cfg
    )

    assert store.refund_count() == 1  # executed exactly once, after the restart
    assert "refund" in final["messages"][-1].content.lower()
    assert any(a["event_type"] == "executed" and a["tool_name"] == "issue_refund" for a in store.audit)


async def test_read_only_flow_auto_executes_without_interrupt():
    store = MemoryStore()
    model = FakeModel([
        AIMessage(content="", tool_calls=[{"name": "get_order", "args": {"order_id": 4471}, "id": "g1"}]),
        AIMessage(content="Order 4471 is $180 and was delivered 3 days ago."),
    ])
    cfg = {"configurable": {"thread_id": "t-read"}}

    out = await build_graph(MemorySaver(), store, model).ainvoke(_init("status of 4471?"), cfg)

    assert "__interrupt__" not in out
    assert "180" in out["messages"][-1].content
    assert any(a["tool_name"] == "get_order" for a in store.audit)


async def test_refund_rejected_does_not_execute():
    store = MemoryStore()
    model = FakeModel([_refund_call("tc_r"), AIMessage(content="I couldn't process that refund.")])
    cfg = {"configurable": {"thread_id": "t-rej"}}
    graph = build_graph(MemorySaver(), store, model)

    await graph.ainvoke(_init("refund order 4471"), cfg)
    await graph.ainvoke(
        Command(resume={"tc_r": {"decision": "reject", "decided_by": "manager", "reason": "out of policy"}}),
        cfg,
    )

    assert store.refund_count() == 0
    assert any(a["event_type"] == "rejected" for a in store.audit)


async def test_refund_modified_executes_with_new_amount():
    store = MemoryStore()
    model = FakeModel([_refund_call("tc_m"), AIMessage(content="A partial refund of $90 was issued.")])
    cfg = {"configurable": {"thread_id": "t-mod"}}
    graph = build_graph(MemorySaver(), store, model)

    await graph.ainvoke(_init("refund order 4471"), cfg)
    await graph.ainvoke(
        Command(resume={"tc_m": {
            "decision": "modify",
            "modified_args": {"order_id": 4471, "amount": 90.0, "reason": "partial"},
            "decided_by": "manager",
        }}),
        cfg,
    )

    assert store.refund_count() == 1
    assert store.refunds[0]["amount"] == 90.0
