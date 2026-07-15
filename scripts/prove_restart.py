"""Prove pause → persist → resume across a REAL process restart — no Docker.

Uses the SQLite-file checkpointer so state outlives the process. Run in two
separate interpreters:

    CHECKPOINT_BACKEND=sqlite PYTHONPATH=src python scripts/prove_restart.py pause
    CHECKPOINT_BACKEND=sqlite PYTHONPATH=src python scripts/prove_restart.py resume

Process 1 pauses at the approval and exits. Process 2 is a brand-new interpreter
(fresh, empty in-memory store) that loads the graph from the SQLite file and
resumes it — the refund executes exactly once, in the second process, proving the
state survived the process boundary.
"""

from __future__ import annotations

import asyncio
import sys

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from app.agent.graph import build_graph
from app.config import settings
from app.db.checkpointer import checkpointer_context
from app.domain.ecommerce import MemoryStore

THREAD = {"configurable": {"thread_id": "restart-demo"}}


class _Fake:
    def __init__(self, msgs):
        self.msgs, self.i = msgs, 0

    def bind_tools(self, *a, **k):
        return self

    async def ainvoke(self, *a, **k):
        m = self.msgs[min(self.i, len(self.msgs) - 1)]
        self.i += 1
        return m


async def pause() -> None:
    store = MemoryStore()
    model = _Fake([AIMessage(content="", tool_calls=[{
        "name": "issue_refund",
        "args": {"order_id": 4471, "amount": 180.0, "reason": "damaged"},
        "id": "tc_restart",
    }])])
    async with checkpointer_context(settings) as cp:
        graph = build_graph(cp, store, model)
        out = await graph.ainvoke(
            {"messages": [HumanMessage("My order 4471 arrived damaged, refund please")],
             "plans": [], "decisions": {}, "user_id": "u", "confidence": 1.0},
            THREAD,
        )
        assert "__interrupt__" in out, "expected a pause at the approval node"
        print(f"[process 1] PAUSED at approval · refunds so far = {store.refund_count()} · "
              f"state persisted to {settings.sqlite_path} · exiting.")


async def resume() -> None:
    store = MemoryStore()  # fresh & empty — nothing carried in memory across processes
    model = _Fake([AIMessage(content="Your $180 refund is processed, 3-5 business days.")])
    async with checkpointer_context(settings) as cp:
        graph = build_graph(cp, store, model)
        snap = await graph.aget_state(THREAD)
        assert snap.interrupts, "no persisted interrupt found — run the 'pause' phase first"
        print(f"[process 2] loaded persisted state in a NEW process · next={snap.next}")
        out = await graph.ainvoke(
            Command(resume={"tc_restart": {"decision": "approve", "decided_by": "manager"}}), THREAD
        )
        print(f"[process 2] RESUMED + executed · refunds now = {store.refund_count()} · "
              f"reply = {out['messages'][-1].content!r}")
        assert store.refund_count() == 1, "refund did not execute exactly once"
        print("[process 2] ✅ exactly-once refund after a real process restart.")


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "pause"
    asyncio.run(pause() if phase == "pause" else resume())
