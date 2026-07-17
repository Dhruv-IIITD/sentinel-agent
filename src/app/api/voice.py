"""RPC surface for the voice worker.

The LiveKit voice agent runs a fast STT -> LLM -> TTS loop and calls these
endpoints as its *tools*.

* **Reads** (`/voice/order`, `/voice/policy`, ...) are plain lookups. They never
  touch the graph, which is what keeps the conversational loop in the low-latency
  hot path.
* **Actions** (`/voice/action`) go through the *real* LangGraph risk gate. The
  voice model has already chosen the tool, so we seed that tool call at the
  `agent` node with `aupdate_state(as_node="agent")` and let the graph take over:
  classify_risk -> (policy/hard-cap/confidence) -> interrupt or execute. That means
  a refund started by *voice* is checkpointed, shows up in the same dashboard
  queue, resumes through the same `Command(resume=...)` path, and is protected by
  the same idempotency ledger as one started by chat. There is no second,
  weaker code path for voice — which is the whole point.

PII note: `/voice/order` deliberately omits the customer's email. The agent has
no reason to speak it aloud, and the caller has already been verified.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException, Request
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from ..tools.registry import REGISTRY
from .chat import finalize
from .serialization import last_reply

router = APIRouter(prefix="/voice", tags=["voice"])

# Only these mutating tools may be driven from a phone call. Reads have their own
# endpoints; anything else is not reachable from the voice surface.
VOICE_ACTIONS = {"issue_refund", "cancel_order", "update_address"}


class VerifyIdentityBody(BaseModel):
    thread_id: str
    order_id: int
    email_or_name: str


def _matches(order: dict, claim: str) -> bool:
    """Demo-grade caller verification: the email on the order, or a name on it.

    Real deployments would use an OTP or an authenticated session; this proves the
    *shape* of the gate (no order details before a successful check).
    """
    claim = claim.strip().lower()
    if not claim:
        return False
    email = (order.get("customer_email") or "").lower()
    name = (order.get("customer_name") or "").lower()
    if email and claim == email:
        return True
    return bool(name) and (claim == name or claim in name.split())


async def _require_verified(request: Request, thread_id: str, order_id: int) -> None:
    """The identity gate, enforced HERE — not only in the voice agent's tools.

    The agent-side check is a fast, friendly refusal; this is the one that actually
    holds. A jailbroken prompt, a buggy worker, or someone curling the API directly
    still cannot read an order or move money on a caller who was never verified.
    Defence in depth: the prompt is not a security boundary, this is.

    The configured verification store is shared across workers when Redis is enabled.
    """
    if not await request.app.state.verification.is_verified(thread_id, order_id):
        raise HTTPException(
            status_code=403,
            detail=f"caller on {thread_id} is not verified for order {order_id}",
        )


@router.post("/verify_identity")
async def verify_identity(body: VerifyIdentityBody, request: Request) -> dict:
    order = await request.app.state.store.get_order(body.order_id)
    if "error" in order:
        return {"verified": False, "reason": "order not found"}
    if not _matches(order, body.email_or_name):
        return {"verified": False, "reason": "those details do not match our records"}

    await request.app.state.verification.mark(body.thread_id, body.order_id)
    return {
        "verified": True,
        "order_id": body.order_id,
        "customer_name": order.get("customer_name"),
    }


@router.get("/order/{order_id}")
async def get_order(order_id: int, request: Request, thread_id: str) -> dict:
    await _require_verified(request, thread_id, order_id)
    order = await request.app.state.store.get_order(order_id)
    if "error" in order:
        return order
    return {k: v for k, v in order.items() if k != "customer_email"}


@router.get("/shipment/{order_id}")
async def track_shipment(order_id: int, request: Request, thread_id: str) -> dict:
    await _require_verified(request, thread_id, order_id)
    return await request.app.state.store.track_shipment(order_id)


@router.get("/refund_eligibility/{order_id}")
async def refund_eligibility(
    order_id: int, request: Request, thread_id: str, amount: float | None = None
) -> dict:
    """Would a refund on this order need a human? Read-only — issues nothing.

    Runs the *same* policy engine that gates the real action, so what the caller
    is told matches what would actually happen.
    """
    await _require_verified(request, thread_id, order_id)
    store = request.app.state.store
    order = await store.get_order(order_id)
    if "error" in order:
        return order

    amt = float(amount) if amount is not None else float(order["amount"])
    decision = request.app.state.policy.decide_refund(amt, order.get("delivered_at"))
    return {
        "order_id": order_id,
        "amount": amt,
        "needs_approval": decision.needs_approval,
        "reason": decision.reason,
        "citation": decision.citation,
    }


@router.get("/policy")
async def search_policy(request: Request, q: str, k: int = 2) -> dict:
    hits = request.app.state.policy.retriever.search(q, k=k)
    return {"clauses": [{"section": h.section, "text": h.text} for h in hits]}


# ---------------------------------------------------------------------------
# Actions — the HITL gate, driven from a voice call
# ---------------------------------------------------------------------------


class TokenBody(BaseModel):
    room: str | None = None
    name: str = "Caller"


@router.post("/token")
async def mint_token(body: TokenBody, request: Request) -> dict:
    """Mint a LiveKit join token for the browser.

    The `thread_id` returned here is the same one the voice worker derives from the
    room name (`voice-<room>`), so the console can follow *this call's* approvals.
    """
    settings = request.app.state.settings
    if not settings.livekit_configured:
        raise HTTPException(
            status_code=503,
            detail="LiveKit is not configured — set LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET.",
        )

    from livekit import api as lk

    room = body.room or f"support-{uuid.uuid4().hex[:8]}"
    identity = f"caller-{uuid.uuid4().hex[:6]}"
    token = (
        lk.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_name(body.name)
        .with_grants(lk.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True))
        .to_jwt()
    )
    return {"token": token, "url": settings.livekit_url, "room": room, "thread_id": f"voice-{room}"}


class ApprovalCallBody(BaseModel):
    phone: str | None = None


@router.post("/approval-call/{approval_id}")
async def approval_call(approval_id: str, body: ApprovalCallBody, request: Request) -> dict:
    """Put a human on a call to decide a pending action — the loop, out loud.

    Dispatches the approver agent into a room; it reads the approval id from the job
    metadata, briefs whoever picks up, takes a spoken decision, and submits it — which
    resumes the paused graph through the same decision endpoint the dashboard uses.

    With a SIP trunk configured this **rings a real phone**. Without one it still runs:
    the room is live and a human joins from the browser. So the feature demos for free
    and becomes a phone call the day a trunk is added — no code change.
    """
    settings = request.app.state.settings
    store = request.app.state.store

    if not settings.livekit_configured:
        raise HTTPException(
            status_code=503,
            detail="LiveKit is not configured — set LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET.",
        )

    row = await store.get_approval(approval_id)
    if row is None:
        raise HTTPException(status_code=404, detail="approval not found")
    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"approval already {row['status']}")

    from livekit import api as lk

    room = f"approval-{approval_id[:12]}"
    phone = body.phone or settings.approver_phone
    dialed = False

    lkapi = lk.LiveKitAPI(settings.livekit_url, settings.livekit_api_key, settings.livekit_api_secret)
    try:
        await lkapi.agent_dispatch.create_dispatch(
            lk.CreateAgentDispatchRequest(
                agent_name=settings.approver_agent_name,
                room=room,
                metadata=json.dumps({"approval_id": approval_id}),
            )
        )
        if settings.livekit_sip_trunk_id and phone:
            await lkapi.sip.create_sip_participant(
                lk.CreateSIPParticipantRequest(
                    sip_trunk_id=settings.livekit_sip_trunk_id,
                    sip_call_to=phone,
                    room_name=room,
                    participant_identity="approver-phone",
                    participant_name="Approver",
                    play_ringtone=True,
                )
            )
            dialed = True
    finally:
        await lkapi.aclose()

    # Always hand back a browser token: it is the no-trunk demo path, and a useful
    # escape hatch when nobody answers the phone.
    token = (
        lk.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(f"approver-{uuid.uuid4().hex[:6]}")
        .with_name("Approver")
        .with_grants(lk.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True))
        .to_jwt()
    )
    return {
        "room": room,
        "dialed": dialed,
        "phone": phone if dialed else None,
        "token": token,
        "url": settings.livekit_url,
        "thread_id": row["thread_id"],
    }


class ActionBody(BaseModel):
    thread_id: str
    tool: str
    args: dict
    user_id: str = "voice-caller"


@router.post("/action")
async def request_action(body: ActionBody, request: Request) -> dict:
    """Run a voice-chosen tool call through the real risk gate.

    Returns either ``executed`` (the policy let it through) or ``approval_required``
    with the queue id the caller is now waiting on — the graph is paused and
    checkpointed at that point, so it survives a backend restart mid-call.
    """
    if body.tool not in VOICE_ACTIONS or body.tool not in REGISTRY:
        raise HTTPException(status_code=422, detail=f"{body.tool} is not callable from voice")

    # No action on an order this caller never proved they own — checked before the
    # graph is even touched, so an unverified refund never reaches the risk gate.
    order_id = body.args.get("order_id")
    if order_id is None:
        raise HTTPException(status_code=422, detail="a voice action must name an order_id")
    await _require_verified(request, body.thread_id, int(order_id))

    graph = request.app.state.graph
    store = request.app.state.store
    cfg = {"configurable": {"thread_id": body.thread_id}}

    # The "call_" prefix is load-bearing, not cosmetic. Resume is delivered as
    # `Command(resume={tool_call_id: decision})`, and LangGraph treats a resume dict
    # whose keys parse as UUIDs as a {task_id: value} map instead of a plain value.
    # A bare uuid4().hex *is* UUID-parseable, so it would silently match no task, the
    # interrupt would re-raise, and the refund would never execute. Real models emit
    # ids like "call_abc123"; we do the same. See tests/test_voice_api.py.
    tool_call_id = f"call_{uuid.uuid4().hex}"

    # The voice model already decided the action; seed it as the agent node's output
    # so the graph's own gate — not a copy of it — decides what happens next.
    await graph.aupdate_state(
        cfg,
        {
            "messages": [AIMessage(content="", tool_calls=[
                {"name": body.tool, "args": body.args, "id": tool_call_id},
            ])],
            "plans": [],
            "decisions": {},
            "user_id": body.user_id,
            "confidence": 1.0,
        },
        as_node="agent",
    )
    result = await graph.ainvoke(None, cfg)
    out = await finalize(graph, store, request.app.state.event_bus, body.thread_id, cfg, result)

    if out["status"] == "awaiting_approval":
        approvals = out["approvals"]
        row = next((a for a in approvals if a["tool_call_id"] == tool_call_id), approvals[0])
        return {
            "status": "approval_required",
            "approval_id": row["id"],
            "tool": row["tool_name"],
            "args": row["tool_args"],
            "citation": row.get("policy_citation"),
        }
    return {"status": "executed", "tool": body.tool, "reply": out.get("reply", "")}


@router.get("/action/{approval_id}")
async def action_status(approval_id: str, request: Request) -> dict:
    """Poll a pending voice action while the caller holds.

    ``settled`` is the flag the agent waits on: the human's decision is recorded
    *before* the graph resumes, so a decided-but-not-yet-executed approval must not
    be reported as done — otherwise we'd tell the caller their refund went through
    a beat before it actually did.
    """
    store = request.app.state.store
    graph = request.app.state.graph

    row = await store.get_approval(approval_id)
    if row is None:
        raise HTTPException(status_code=404, detail="approval not found")
    if row["status"] == "pending":
        return {"status": "pending", "settled": False}

    state = await graph.aget_state({"configurable": {"thread_id": row["thread_id"]}})
    if state.interrupts:  # decided, but the graph hasn't finished resuming yet
        return {"status": row["status"], "settled": False}

    return {
        "status": row["status"],
        "settled": True,
        "reply": last_reply((state.values or {}).get("messages", [])),
        "reason": row.get("reason"),
    }
