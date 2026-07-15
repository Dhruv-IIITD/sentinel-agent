"""The operational metrics are derived from the audit log + approval queue, so they
should be true by construction. This drives real actions through the real graph and
checks the arithmetic — including the one that matters most on a voice call:
time-to-decision, which is how long the caller was on hold.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import build_graph
from app.domain.ecommerce import MemoryStore
from app.main import app
from tests.fakes import FakeModel

CALL = "m-call"


def _setup(client: TestClient) -> MemoryStore:
    store = MemoryStore()
    app.state.store = store
    app.state.verified = {}
    app.state.graph = build_graph(
        MemorySaver(), store, FakeModel([]), policy=app.state.policy, hard_cap=1000.0
    )
    client.post(
        "/voice/verify_identity",
        json={"thread_id": CALL, "order_id": 4471, "email_or_name": "alice@example.com"},
    )
    return store


def _act(client: TestClient, tool: str, args: dict) -> dict:
    return client.post(
        "/voice/action", json={"thread_id": CALL, "tool": tool, "args": args}
    ).json()


def test_metrics_are_empty_before_anything_happens():
    with TestClient(app) as client:
        _setup(client)
        m = client.get("/metrics").json()
        assert m["autonomy_rate"] is None  # no actions -> no rate, not a fake 0
        assert m["override_rate"] is None
        assert m["time_to_decision_s"]["p50"] is None
        assert m["actions"]["auto_executed"] == 0


def test_autonomy_override_and_time_to_decision():
    with TestClient(app) as client:
        _setup(client)

        # 1. an action the agent handled alone (inside policy)
        assert _act(client, "issue_refund", {"order_id": 4471, "amount": 20.0, "reason": "x"})[
            "status"
        ] == "executed"

        # 2. one a human approved
        gated = _act(client, "issue_refund", {"order_id": 4471, "amount": 180.0, "reason": "y"})
        client.post(f"/approvals/{gated['approval_id']}/decision", json={"decision": "approve"})

        # 3. one a human declined
        declined = _act(client, "cancel_order", {"order_id": 4471, "reason": "z"})
        client.post(
            f"/approvals/{declined['approval_id']}/decision",
            json={"decision": "reject", "reason": "no"},
        )

        m = client.get("/metrics").json()

        assert m["actions"]["auto_executed"] == 1
        assert m["actions"]["executed_after_approval"] == 1
        assert m["actions"]["declined_by_human"] == 1

        # 1 of the 3 concluded actions needed no human at all
        assert m["autonomy_rate"] == round(1 / 3, 3)
        # 1 of the 2 human decisions overruled the agent
        assert m["override_rate"] == 0.5
        assert m["approvals"] == {"pending": 0, "decided": 2, "rejected": 1, "modified": 0}

        # the caller's hold time is real and non-negative
        ttd = m["time_to_decision_s"]
        assert ttd["p50"] is not None and ttd["p50"] >= 0
        assert ttd["max"] >= ttd["p50"]

        # tool latency is actually recorded now (it used to be a field nothing wrote)
        assert m["tool_latency_ms"]["p50"] is not None


def test_reversal_is_counted():
    with TestClient(app) as client:
        store = _setup(client)
        _act(client, "issue_refund", {"order_id": 4471, "amount": 20.0, "reason": "x"})

        key = next(
            a["idempotency_key"]
            for a in client.get("/audit").json()
            if a["event_type"] == "executed" and a.get("idempotency_key")
        )
        client.post(f"/compensate/{key}", json={"reason": "customer error"})

        assert client.get("/metrics").json()["actions"]["reversed"] == 1
        assert store.refunds[0]["status"] == "reversed"


def test_pending_approval_has_no_decision_time_yet():
    with TestClient(app) as client:
        _setup(client)
        _act(client, "issue_refund", {"order_id": 4471, "amount": 180.0, "reason": "y"})

        m = client.get("/metrics").json()
        assert m["approvals"]["pending"] == 1
        assert m["approvals"]["decided"] == 0
        assert m["time_to_decision_s"]["p50"] is None  # still holding
        assert m["override_rate"] is None
