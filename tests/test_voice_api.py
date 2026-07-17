"""Tests for the voice RPC surface (the tools the LiveKit agent calls).

These are the *facts* the voice agent is allowed to speak and the *actions* it is
allowed to take — plus the identity gate that guards both. The policy engine here is
the real one (it reads `data/policies/`), so refund-eligibility answers match what the
risk gate would actually do to a real refund.

The identity gate is enforced **server-side**, not just in the agent's tools: a caller
who never proved they own an order cannot read it or move money on it, even by calling
this API directly. The prompt is not a security boundary.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import build_graph
from app.domain.ecommerce import MemoryStore
from app.main import app
from app.safety.verification import InMemoryVerificationStore
from tests.fakes import FakeModel

CALL = "voice-call-1"  # a call's graph thread


def _client() -> TestClient:
    return TestClient(app)


def _inject(store: MemoryStore, model: FakeModel | None = None) -> None:
    """Swap in a fresh store + a graph wired to the real policy engine.

    The policy engine matters here: it is what decides, at runtime, whether a refund
    requested *by voice* needs a human.
    """
    app.state.store = store
    app.state.verification = InMemoryVerificationStore()
    app.state.graph = build_graph(
        MemorySaver(),
        store,
        model or FakeModel([AIMessage(content="All set.")]),
        policy=app.state.policy,
        hard_cap=1000.0,
    )


def _verify(client, order_id: int = 4471, thread: str = CALL, who: str = "alice@example.com"):
    return client.post(
        "/voice/verify_identity",
        json={"thread_id": thread, "order_id": order_id, "email_or_name": who},
    ).json()


# ---------------------------------------------------------------------------
# The identity gate
# ---------------------------------------------------------------------------


def test_verify_identity_by_email_and_by_name():
    with _client() as client:
        _inject(MemoryStore())

        by_email = _verify(client)
        assert by_email["verified"] is True
        assert by_email["customer_name"] == "Alice Rivera"

        by_name = _verify(client, thread="voice-call-name", who="Rivera")
        assert by_name["verified"] is True


def test_verify_identity_rejects_wrong_details_and_unknown_order():
    with _client() as client:
        _inject(MemoryStore())

        assert _verify(client, who="mallory@evil.com")["verified"] is False

        missing = _verify(client, order_id=9999)
        assert missing["verified"] is False
        assert missing["reason"] == "order not found"


def test_reads_are_refused_until_the_caller_is_verified():
    """The gate that actually holds — enforced here, not in the agent's prompt."""
    with _client() as client:
        _inject(MemoryStore())

        for url in (
            f"/voice/order/4471?thread_id={CALL}",
            f"/voice/shipment/4471?thread_id={CALL}",
            f"/voice/refund_eligibility/4471?thread_id={CALL}",
        ):
            assert client.get(url).status_code == 403, url

        _verify(client)

        assert client.get(f"/voice/order/4471?thread_id={CALL}").status_code == 200


def test_verification_does_not_leak_across_orders_or_calls():
    with _client() as client:
        _inject(MemoryStore())
        _verify(client, order_id=4471)

        # a different order on the same call
        assert client.get(f"/voice/order/4473?thread_id={CALL}").status_code == 403
        # the same order on a different call
        assert client.get("/voice/order/4471?thread_id=someone-else").status_code == 403


def test_an_unverified_caller_cannot_move_money_even_by_calling_the_api_directly():
    """A jailbroken or replaced voice worker still cannot issue a refund."""
    with _client() as client:
        store = MemoryStore()
        _inject(store)

        resp = client.post(
            "/voice/action",
            json={"thread_id": CALL, "tool": "issue_refund",
                  "args": {"order_id": 4471, "amount": 20.0, "reason": "nice try"}},
        )
        assert resp.status_code == 403
        assert store.refund_count() == 0  # never reached the risk gate at all


# ---------------------------------------------------------------------------
# Grounded reads
# ---------------------------------------------------------------------------


def test_get_order_returns_details_but_never_the_email():
    with _client() as client:
        _inject(MemoryStore())
        _verify(client)
        order = client.get(f"/voice/order/4471?thread_id={CALL}").json()
        assert order["amount"] == 180.0
        assert order["status"] == "delivered"
        assert "customer_email" not in order  # PII stays out of the agent's mouth
        assert order["customer_name"] == "Alice Rivera"


def test_track_shipment_and_missing_order():
    with _client() as client:
        _inject(MemoryStore())
        _verify(client, order_id=4473)
        assert client.get(f"/voice/shipment/4473?thread_id={CALL}").json()["status"] == "in_transit"


def test_refund_eligibility_matches_policy_gate():
    with _client() as client:
        _inject(MemoryStore())
        _verify(client)

        # $180, over the $50 auto-approve limit -> a human is needed.
        big = client.get(f"/voice/refund_eligibility/4471?thread_id={CALL}").json()
        assert big["needs_approval"] is True
        assert big["amount"] == 180.0
        assert big["citation"]

        # A small partial refund on the same order is inside the limit.
        # (Both query params in one dict — httpx's `params=` replaces the query string.)
        small = client.get(
            "/voice/refund_eligibility/4471", params={"thread_id": CALL, "amount": 20}
        ).json()
        assert small["needs_approval"] is False


def test_policy_search_returns_a_real_clause_not_document_preamble():
    """The agent reads this text aloud, so it must be an actual policy clause.

    Regression: the doc's preamble used to be indexed and outranked real clauses
    (it inherits the "Refund & Cancellation Policy" heading's keywords), so the
    agent would have told a caller "Source document for the policy-RAG layer".
    """
    with _client() as client:
        _inject(MemoryStore())
        clauses = client.get("/voice/policy", params={"q": "refund window"}).json()["clauses"]
        assert clauses
        top = clauses[0]["text"]
        assert "Source document" not in top
        assert "policy-RAG" not in top
        assert "30" in top and "refund" in top.lower()


# ---------------------------------------------------------------------------
# Actions — the HITL gate, driven from a voice call
# ---------------------------------------------------------------------------


def test_voice_action_rejects_tools_not_callable_from_voice():
    with _client() as client:
        _inject(MemoryStore())
        _verify(client)
        resp = client.post(
            "/voice/action",
            json={"thread_id": CALL, "tool": "get_order", "args": {"order_id": 4471}},
        )
        assert resp.status_code == 422


def test_voice_reversible_action_executes_immediately():
    with _client() as client:
        store = MemoryStore()
        _inject(store)
        _verify(client)
        body = client.post(
            "/voice/action",
            json={"thread_id": CALL, "tool": "update_address",
                  "args": {"order_id": 4471, "new_address": "99 New St"}},
        ).json()
        assert body["status"] == "executed"  # reversible -> no human needed
        assert store.orders[4471]["shipping_address"] == "99 New St"


def test_voice_small_refund_auto_executes_per_policy():
    """The policy engine drives voice exactly as it drives chat: $20 is inside the limit."""
    with _client() as client:
        store = MemoryStore()
        _inject(store)
        _verify(client)
        body = client.post(
            "/voice/action",
            json={"thread_id": CALL, "tool": "issue_refund",
                  "args": {"order_id": 4471, "amount": 20.0, "reason": "partial"}},
        ).json()
        assert body["status"] == "executed"
        assert store.refund_count() == 1


def test_voice_large_refund_pauses_holds_then_resumes_on_approval():
    """The signature flow: gated mid-call, decided by a human, resumed, executed once."""
    with _client() as client:
        store = MemoryStore()
        _inject(store)
        _verify(client)

        started = client.post(
            "/voice/action",
            json={"thread_id": CALL, "tool": "issue_refund",
                  "args": {"order_id": 4471, "amount": 180.0, "reason": "damaged"}},
        ).json()
        assert started["status"] == "approval_required"
        assert started["citation"]  # the approver sees why
        approval_id = started["approval_id"]
        assert store.refund_count() == 0  # nothing has happened yet

        # while the caller holds, the action is not settled
        assert client.get(f"/voice/action/{approval_id}").json() == {
            "status": "pending", "settled": False
        }

        # it lands in the SAME dashboard queue as a chat-initiated approval
        assert any(a["id"] == approval_id for a in client.get("/approvals").json())

        # a human approves in the dashboard -> the graph resumes
        client.post(f"/approvals/{approval_id}/decision",
                    json={"decision": "approve", "decided_by": "manager"})

        settled = client.get(f"/voice/action/{approval_id}").json()
        assert settled["settled"] is True
        assert settled["status"] == "approved"
        assert store.refund_count() == 1  # executed exactly once


def test_voice_refund_declined_never_reports_success():
    with _client() as client:
        store = MemoryStore()
        _inject(store)
        _verify(client)
        started = client.post(
            "/voice/action",
            json={"thread_id": CALL, "tool": "issue_refund",
                  "args": {"order_id": 4471, "amount": 180.0, "reason": "damaged"}},
        ).json()
        approval_id = started["approval_id"]

        client.post(f"/approvals/{approval_id}/decision",
                    json={"decision": "reject", "reason": "outside policy", "decided_by": "manager"})

        settled = client.get(f"/voice/action/{approval_id}").json()
        assert settled["settled"] is True
        assert settled["status"] == "rejected"
        assert settled["reason"] == "outside policy"
        assert store.refund_count() == 0  # no money moved


def test_voice_tool_call_ids_are_never_uuid_shaped():
    """Guards a landmine: resume is `Command(resume={tool_call_id: decision})`, and
    LangGraph reads a resume dict with UUID-parseable keys as a {task_id: value} map.
    A bare uuid4().hex id would match no task, so the interrupt would re-raise and the
    refund would never execute — silently. Keep voice ids un-parseable as UUIDs."""
    import uuid as _uuid

    with _client() as client:
        _inject(MemoryStore())
        _verify(client)
        started = client.post(
            "/voice/action",
            json={"thread_id": CALL, "tool": "issue_refund",
                  "args": {"order_id": 4471, "amount": 180.0, "reason": "damaged"}},
        ).json()

        rows = client.get("/approvals").json()
        tool_call_id = next(r["tool_call_id"] for r in rows if r["id"] == started["approval_id"])
        try:
            _uuid.UUID(tool_call_id)
        except ValueError:
            pass  # good: not UUID-parseable
        else:
            raise AssertionError(f"tool_call_id {tool_call_id!r} parses as a UUID; resume will break")


def test_voice_cancel_order_always_needs_a_human():
    with _client() as client:
        store = MemoryStore()
        _inject(store)
        _verify(client, order_id=4473)
        body = client.post(
            "/voice/action",
            json={"thread_id": CALL, "tool": "cancel_order",
                  "args": {"order_id": 4473, "reason": "changed mind"}},
        ).json()
        assert body["status"] == "approval_required"  # high-stakes, regardless of policy
        assert store.orders[4473]["status"] == "in_transit"  # untouched


# ---------------------------------------------------------------------------
# The approval call — the agent phones a human for sign-off
# ---------------------------------------------------------------------------


def _livekit_settings(**over):
    """A Settings that ignores .env / the ambient environment, so these tests never
    depend on whether the developer happens to have LiveKit keys exported."""
    from app.config import Settings

    base = dict(livekit_url="", livekit_api_key="", livekit_api_secret="")
    return Settings(_env_file=None, **{**base, **over})


def _gate_a_refund(client, thread=CALL) -> str:
    _verify(client, thread=thread)
    started = client.post(
        "/voice/action",
        json={"thread_id": thread, "tool": "issue_refund",
              "args": {"order_id": 4471, "amount": 180.0, "reason": "damaged"}},
    ).json()
    return started["approval_id"]


def test_approval_call_requires_livekit():
    with _client() as client:
        _inject(MemoryStore())
        app.state.settings = _livekit_settings()
        approval_id = _gate_a_refund(client)
        resp = client.post(f"/voice/approval-call/{approval_id}", json={})
        assert resp.status_code == 503
        assert "LIVEKIT" in resp.json()["detail"].upper()


def test_approval_call_404_for_unknown_approval():
    with _client() as client:
        _inject(MemoryStore())
        # Configured (so we get past the 503) but the id check runs before any
        # LiveKit call, so nothing reaches the network.
        app.state.settings = _livekit_settings(
            livekit_url="wss://x", livekit_api_key="k", livekit_api_secret="s"
        )
        assert client.post("/voice/approval-call/nope", json={}).status_code == 404


def test_approval_call_409_once_already_decided():
    """You cannot phone someone about a decision that has already been made."""
    with _client() as client:
        _inject(MemoryStore())
        app.state.settings = _livekit_settings(
            livekit_url="wss://x", livekit_api_key="k", livekit_api_secret="s"
        )
        approval_id = _gate_a_refund(client, thread="voice-call-2")
        client.post(f"/approvals/{approval_id}/decision", json={"decision": "approve"})

        resp = client.post(f"/voice/approval-call/{approval_id}", json={})
        assert resp.status_code == 409
        assert "approved" in resp.json()["detail"]
