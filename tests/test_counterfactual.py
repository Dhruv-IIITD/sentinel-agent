"""Counterfactual replay: fork a paused approval into approve + reject branches."""

from __future__ import annotations

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import build_graph
from app.domain.ecommerce import MemoryStore
from app.main import app
from tests.fakes import FakeModel


def _refund(call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{
        "name": "issue_refund",
        "args": {"order_id": 4471, "amount": 180.0, "reason": "x"},
        "id": call_id,
    }])


def test_counterfactual_plays_out_both_branches_without_mutating_real_state():
    store = MemoryStore()
    model = FakeModel([_refund("tcf"), AIMessage(content="base done")])
    with TestClient(app) as client:
        app.state.store = store
        app.state.graph = build_graph(MemorySaver(), store, model)
        # A fresh single-reply model per branch.
        app.state.model_factory = lambda: FakeModel([AIMessage(content="branch reply")])

        client.post("/chat", json={"message": "refund order 4471", "thread_id": "cf1"})
        res = client.post("/threads/cf1/counterfactual")
        assert res.status_code == 200, res.text
        body = res.json()

        assert set(body["outcomes"]) == {"approve", "reject"}
        # approve branch issues a refund in its sandbox; reject changes nothing.
        assert body["outcomes"]["approve"]["effects"].get("refunds", {}).get("after") == 1
        assert body["outcomes"]["reject"]["effects"] == {}

        # The real thread + store are untouched, and the original approval is still pending.
        assert store.refund_count() == 0
        assert len(client.get("/approvals").json()) == 1
