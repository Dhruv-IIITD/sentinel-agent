"""The SQLite checkpointer survives a 'restart' — a fresh context on the same file.

This exercises the same persistence path the two-process `scripts/prove_restart.py`
demonstrates, but within one test so CI covers it.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from app.agent.graph import build_graph
from app.config import Settings
from app.db.checkpointer import checkpointer_context
from app.domain.ecommerce import MemoryStore
from tests.fakes import FakeModel


async def test_sqlite_pause_persist_resume_across_contexts(tmp_path):
    settings = Settings(
        checkpoint_backend="sqlite", sqlite_path=str(tmp_path / "cp.sqlite"), database_url=""
    )
    thread = {"configurable": {"thread_id": "t"}}
    refund_call = AIMessage(content="", tool_calls=[{
        "name": "issue_refund", "args": {"order_id": 4471, "amount": 180.0, "reason": "x"}, "id": "tc",
    }])

    # --- "process 1": pause and close the checkpointer ---
    store_a = MemoryStore()
    async with checkpointer_context(settings) as cp_a:
        graph_a = build_graph(cp_a, store_a, FakeModel([refund_call]))
        out = await graph_a.ainvoke(
            {"messages": [HumanMessage("refund 4471")], "plans": [], "decisions": {},
             "user_id": "u", "confidence": 1.0},
            thread,
        )
        assert "__interrupt__" in out
        assert store_a.refund_count() == 0

    # --- "process 2": fresh context on the same file + a fresh store ---
    store_b = MemoryStore()
    async with checkpointer_context(settings) as cp_b:
        graph_b = build_graph(cp_b, store_b, FakeModel([AIMessage(content="done")]))
        snapshot = await graph_b.aget_state(thread)
        assert snapshot.interrupts  # the pause survived
        await graph_b.ainvoke(Command(resume={"tc": {"decision": "approve", "decided_by": "m"}}), thread)
        assert store_b.refund_count() == 1  # executed exactly once, after the "restart"
