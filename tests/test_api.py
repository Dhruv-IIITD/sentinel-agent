"""End-to-end API tests for the chat + approval + audit flow.

The graph and store are swapped for a fake model + MemoryStore after the app's
lifespan starts, so these exercise the real endpoints without the network or a DB.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import build_graph
from app.domain.ecommerce import MemoryStore
from app.main import app
from tests.fakes import FakeModel


def _refund_msg(call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{
        "name": "issue_refund",
        "args": {"order_id": 4471, "amount": 180.0, "reason": "damaged"},
        "id": call_id,
    }])


def _inject(store: MemoryStore, model: FakeModel) -> None:
    app.state.store = store
    app.state.graph = build_graph(MemorySaver(), store, model)


def test_chat_refund_approval_flow():
    store = MemoryStore()
    model = FakeModel([_refund_msg("tc1"), AIMessage(content="Your $180 refund is processed.")])
    with TestClient(app) as client:
        _inject(store, model)

        resp = client.post("/chat", json={"message": "refund order 4471", "thread_id": "api-t1"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "awaiting_approval"
        assert len(body["approvals"]) == 1
        approval = body["approvals"][0]
        assert approval["tool_name"] == "issue_refund"
        assert approval["status"] == "pending"
        assert store.refund_count() == 0  # nothing executed yet

        # queue endpoint shows it
        queue = client.get("/approvals").json()
        assert any(a["id"] == approval["id"] for a in queue)

        # approve -> graph resumes, refund executes exactly once
        decision = client.post(f"/approvals/{approval['id']}/decision",
                               json={"decision": "approve", "decided_by": "manager"})
        assert decision.status_code == 200, decision.text
        dbody = decision.json()
        assert dbody["status"] == "completed"
        assert "refund" in dbody["reply"].lower()
        assert store.refund_count() == 1

        # audit + thread history reflect it
        audit = client.get("/audit", params={"thread_id": "api-t1"}).json()
        assert any(a["event_type"] == "executed" for a in audit)
        thread = client.get("/threads/api-t1").json()
        assert thread["awaiting_approval"] is False
        assert len(thread["messages"]) >= 2

        # deciding again is a conflict
        again = client.post(f"/approvals/{approval['id']}/decision", json={"decision": "approve"})
        assert again.status_code == 409


def test_chat_refund_reject_flow():
    store = MemoryStore()
    model = FakeModel([_refund_msg("tc2"), AIMessage(content="I couldn't process that refund.")])
    with TestClient(app) as client:
        _inject(store, model)
        approval = client.post("/chat", json={"message": "refund order 4471", "thread_id": "api-t2"}).json()["approvals"][0]
        decision = client.post(f"/approvals/{approval['id']}/decision",
                               json={"decision": "reject", "reason": "out of policy", "decided_by": "manager"})
        assert decision.status_code == 200
        assert decision.json()["status"] == "completed"
        assert store.refund_count() == 0
        assert any(a["event_type"] == "rejected" for a in store.audit)


def test_chat_read_only_completes_without_approval():
    store = MemoryStore()
    model = FakeModel([
        AIMessage(content="", tool_calls=[{"name": "get_order", "args": {"order_id": 4471}, "id": "g1"}]),
        AIMessage(content="Order 4471 is $180 and was delivered."),
    ])
    with TestClient(app) as client:
        _inject(store, model)
        body = client.post("/chat", json={"message": "status of 4471", "thread_id": "api-ro"}).json()
        assert body["status"] == "completed"
        assert "180" in body["reply"]


def test_decision_on_missing_approval_is_404():
    with TestClient(app) as client:
        _inject(MemoryStore(), FakeModel([]))
        resp = client.post("/approvals/deadbeef/decision", json={"decision": "approve"})
        assert resp.status_code == 404


def test_dashboard_is_served_and_root_redirects():
    with TestClient(app) as client:
        _inject(MemoryStore(), FakeModel([]))
        redirect = client.get("/", follow_redirects=False)
        assert redirect.status_code in (307, 308)
        assert redirect.headers["location"] == "/ui/"
        page = client.get("/ui/")
        assert page.status_code == 200
        # Either console may be mounted: the built React app (web/dist) when the
        # frontend has been built, else the dependency-free ui/ fallback.
        assert "HITL Agent" in page.text


def test_compensate_endpoint_reverses_executed_refund():
    store = MemoryStore()
    model = FakeModel([_refund_msg("tcc"), AIMessage(content="done")])
    with TestClient(app) as client:
        _inject(store, model)
        approval = client.post("/chat", json={"message": "refund order 4471", "thread_id": "cx"}).json()["approvals"][0]
        client.post(f"/approvals/{approval['id']}/decision", json={"decision": "approve"})
        assert store.refund_count() == 1

        audit = client.get("/audit", params={"thread_id": "cx"}).json()
        key = next(a["idempotency_key"] for a in audit
                   if a["event_type"] == "executed" and a.get("idempotency_key"))
        res = client.post(f"/compensate/{key}", json={"reason": "customer error"})
        assert res.status_code == 200
        assert res.json()["status"] == "compensated"
        assert store.refunds[0]["status"] == "reversed"


def test_chat_stream_emits_steps_and_pauses():
    store = MemoryStore()
    model = FakeModel([_refund_msg("tcs"), AIMessage(content="done")])
    with TestClient(app) as client:
        _inject(store, model)
        resp = client.post("/chat/stream", json={"message": "refund order 4471", "thread_id": "sx"})
        assert resp.status_code == 200
        assert "issue_refund" in resp.text
        assert "approval_required" in resp.text
        assert len(client.get("/approvals").json()) >= 1
