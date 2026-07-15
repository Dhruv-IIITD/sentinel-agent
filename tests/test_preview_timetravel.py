"""Decision outcome preview (dry-run) + the time-travel checkpoint inspector."""

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


def _inject(store: MemoryStore, model: FakeModel) -> None:
    app.state.store = store
    app.state.graph = build_graph(MemorySaver(), store, model)


async def test_dry_run_previews_effect_without_mutating():
    store = MemoryStore()
    out = await store.dry_run("issue_refund", {"order_id": 4471, "amount": 180.0, "reason": "x"})
    assert out["simulated"] is True
    assert out["effects"]["refunds"]["after"] == out["effects"]["refunds"]["before"] + 1
    assert store.refund_count() == 0  # the real store was untouched


def test_preview_endpoint_shows_both_outcomes():
    store = MemoryStore()
    model = FakeModel([_refund("tcp"), AIMessage(content="done")])
    with TestClient(app) as client:
        _inject(store, model)
        approval = client.post("/chat", json={"message": "refund order 4471", "thread_id": "pv"}).json()["approvals"][0]
        preview = client.get(f"/approvals/{approval['id']}/preview").json()

        assert preview["outcomes"]["approve"]["executes"] is True
        assert "refunds" in preview["outcomes"]["approve"]["effects"]
        assert preview["outcomes"]["reject"]["executes"] is False
        assert store.refund_count() == 0  # previewing didn't execute anything


def test_thread_history_exposes_checkpoints():
    store = MemoryStore()
    model = FakeModel([_refund("tch"), AIMessage(content="done")])
    with TestClient(app) as client:
        _inject(store, model)
        client.post("/chat", json={"message": "refund order 4471", "thread_id": "hx"})
        history = client.get("/threads/hx/history").json()["checkpoints"]

        assert len(history) >= 3  # __start__ -> agent -> classify -> paused
        assert history[0]["next"] == ["human_approval"]  # newest = the paused point
