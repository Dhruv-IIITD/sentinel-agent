"""The voice support agent — grounded reads, real actions, and a human in the loop.

Three things worth knowing:

* **The identity gate is enforced twice.** Here in the tool layer it is a fast,
  friendly refusal — but the check that actually *holds* is server-side: the backend
  403s any order read or action on a caller who never proved they own the order (see
  `api/voice.py::_require_verified`). So a jailbroken prompt, a buggy worker, or
  someone curling the API directly still cannot read an order or move money. The
  prompt is not a security boundary.
* **Actions do not execute here.** `issue_refund` / `cancel_order` post the tool
  call to the backend, which runs it through the real LangGraph risk gate. If the
  policy gates it, the graph pauses (checkpointed) and we hold the caller while a
  human decides in the dashboard — then resume and speak the outcome.
* **The agent may never claim success on its own.** Tools return an explicit
  DONE / APPROVED / DECLINED / PENDING verdict, and the prompt forbids inventing
  one. The worst failure mode on a support call is telling someone their money is
  on the way when it isn't.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from livekit.agents import Agent, RunContext, function_tool

from backend import Backend

# Policy clauses are markdown; emphasis markers must not reach the TTS engine.
_MARKDOWN = re.compile(r"\*\*|__|[*`]")

# How long we keep a caller on hold waiting for a supervisor, and how often we
# check / reassure them. A silent line is a hung-up line.
APPROVAL_TIMEOUT_S = 120.0
POLL_INTERVAL_S = 1.5
REASSURE_EVERY_S = 25.0

INSTRUCTIONS = (
    "You are a warm, concise voice customer-support agent for an online store. "
    "You are on a phone call: speak naturally, one or two short sentences, never use "
    "lists or markdown, and say numbers as words (say 'order four four seven one' and "
    "'one hundred eighty dollars').\n\n"
    "SECURITY: before you share ANY detail about an order, or take ANY action on it, "
    "verify the caller. Ask for the order number and the email address or name on the "
    "order, then call verify_identity. If it fails, apologize and reveal nothing.\n\n"
    "GROUNDING: only state facts your tools return. Never invent an order, amount, "
    "date, or policy.\n\n"
    "ACTIONS: you can issue refunds, cancel orders, and update a shipping address. "
    "Always confirm the amount and the reason with the caller before you issue a refund. "
    "NEVER tell the caller an action succeeded unless the tool result says DONE or "
    "APPROVED. If a tool says a supervisor is reviewing it, tell them you're waiting and "
    "stay with them. If it says DECLINED, apologize, give the reason, and offer to help "
    "another way. If it says PENDING, explain you'll follow up — do not promise it went "
    "through."
)


@dataclass
class CallState:
    """Per-call state, carried in AgentSession.userdata."""

    backend: Backend
    thread_id: str
    verified_orders: set[int] = field(default_factory=set)
    customer_name: str | None = None


def _unverified(order_id: int) -> str:
    return (
        f"NOT_VERIFIED: the caller is not verified for order {order_id}. Ask for the order "
        "number and the email or name on the order, then call verify_identity. Reveal nothing "
        "and take no action."
    )


def _delivery_phrase(iso: str | None) -> str:
    if not iso:
        return "not yet delivered"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return "delivery date unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - dt).days
    if days <= 0:
        return "delivered today"
    if days == 1:
        return "delivered yesterday"
    return f"delivered {days} days ago"


class SupportAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=INSTRUCTIONS)

    # --- reads -------------------------------------------------------------

    @function_tool
    async def verify_identity(
        self, ctx: RunContext[CallState], order_id: int, email_or_name: str
    ) -> str:
        """Verify the caller owns an order. Needs the order number and the email address
        or the name on the order. Must succeed before any order is discussed or acted on."""
        res = await ctx.userdata.backend.verify_identity(ctx.userdata.thread_id, order_id, email_or_name)
        if not res.get("verified"):
            return f"Verification failed: {res.get('reason', 'no match')}. Do not reveal order details."
        ctx.userdata.verified_orders.add(order_id)
        ctx.userdata.customer_name = res.get("customer_name")
        return f"Verified {res.get('customer_name')} for order {order_id}. You may discuss this order now."

    @function_tool
    async def get_order_status(self, ctx: RunContext[CallState], order_id: int) -> str:
        """Look up an order: the item, the amount, its status, and when it was delivered.
        The caller must be verified for this order first."""
        if order_id not in ctx.userdata.verified_orders:
            return _unverified(order_id)
        o = await ctx.userdata.backend.get_order(ctx.userdata.thread_id, order_id)
        if "error" in o:
            return f"No order {order_id} was found."
        return (
            f"Order {order_id}: {o.get('item_description')}, {o.get('amount')} dollars, "
            f"status {o.get('status')}, {_delivery_phrase(o.get('delivered_at'))}."
        )

    @function_tool
    async def track_shipment(self, ctx: RunContext[CallState], order_id: int) -> str:
        """Get the current shipment/tracking status for an order.
        The caller must be verified for this order first."""
        if order_id not in ctx.userdata.verified_orders:
            return _unverified(order_id)
        s = await ctx.userdata.backend.track_shipment(ctx.userdata.thread_id, order_id)
        if "error" in s:
            return f"No order {order_id} was found."
        return f"Order {order_id} is {s.get('status')} with carrier {s.get('carrier')}."

    @function_tool
    async def check_refund_eligibility(
        self, ctx: RunContext[CallState], order_id: int, amount: float | None = None
    ) -> str:
        """Check whether a refund on this order would be approved automatically or would
        need a human supervisor. READ-ONLY: this does not issue a refund. Defaults to the
        full order amount. The caller must be verified for this order first."""
        if order_id not in ctx.userdata.verified_orders:
            return _unverified(order_id)
        r = await ctx.userdata.backend.refund_eligibility(ctx.userdata.thread_id, order_id, amount)
        if "error" in r:
            return f"No order {order_id} was found."
        gate = (
            "would need a supervisor's approval"
            if r["needs_approval"]
            else "can be approved automatically"
        )
        return (
            f"A {r['amount']} dollar refund on order {order_id} {gate}. "
            f"Policy reason: {r['reason']}."
        )

    @function_tool
    async def get_refund_policy(self, ctx: RunContext[CallState], question: str) -> str:
        """Quote the store's refund and returns policy. Use for general policy questions.
        No verification needed — the policy is public."""
        res = await ctx.userdata.backend.search_policy(question)
        clauses = res.get("clauses") or []
        if not clauses:
            return "I couldn't find a policy clause covering that."
        return _MARKDOWN.sub("", " ".join(c["text"] for c in clauses[:2]))[:600].strip()

    # --- actions (routed through the backend's HITL risk gate) -------------

    @function_tool
    async def issue_refund(
        self, ctx: RunContext[CallState], order_id: int, amount: float, reason: str = ""
    ) -> str:
        """Issue a refund against an order. Refunds within policy go through immediately;
        larger or out-of-window ones need a human supervisor, and the caller will hold while
        you wait. Confirm the amount and reason with the caller first. The caller must be
        verified for this order."""
        if order_id not in ctx.userdata.verified_orders:
            return _unverified(order_id)
        return await self._act(
            ctx, "issue_refund", {"order_id": order_id, "amount": amount, "reason": reason}
        )

    @function_tool
    async def cancel_order(
        self, ctx: RunContext[CallState], order_id: int, reason: str = ""
    ) -> str:
        """Cancel an order. This always needs a human supervisor's approval, so the caller
        will hold while you wait. The caller must be verified for this order."""
        if order_id not in ctx.userdata.verified_orders:
            return _unverified(order_id)
        return await self._act(ctx, "cancel_order", {"order_id": order_id, "reason": reason})

    @function_tool
    async def update_shipping_address(
        self, ctx: RunContext[CallState], order_id: int, new_address: str
    ) -> str:
        """Change the shipping address on an order. Reversible, so it takes effect right
        away. The caller must be verified for this order."""
        if order_id not in ctx.userdata.verified_orders:
            return _unverified(order_id)
        return await self._act(
            ctx, "update_address", {"order_id": order_id, "new_address": new_address}
        )

    # --- the human-in-the-loop wait ---------------------------------------

    async def _act(self, ctx: RunContext[CallState], tool: str, args: dict) -> str:
        res = await ctx.userdata.backend.request_action(ctx.userdata.thread_id, tool, args)
        status = res.get("status")
        if status == "executed":
            return f"DONE: {res.get('reply') or f'{tool} completed'}"
        if status == "approval_required":
            return await self._hold_for_approval(ctx, res["approval_id"])
        return "The action did not go through. Apologize and offer to connect a human teammate."

    async def _hold_for_approval(self, ctx: RunContext[CallState], approval_id: str) -> str:
        """Speak first, then block. The caller must never sit in silence wondering."""
        ctx.session.say(
            "That one needs a quick approval from my supervisor. "
            "Let me get that for you — just a moment."
        )

        started = time.monotonic()
        last_reassured = started
        while time.monotonic() - started < APPROVAL_TIMEOUT_S:
            state = await ctx.userdata.backend.action_status(approval_id)
            if state.get("settled"):
                if state["status"] in ("approved", "modified"):
                    return f"APPROVED: {state.get('reply') or 'the action went through.'}"
                return (
                    f"DECLINED by the supervisor. Reason: {state.get('reason') or 'not given'}. "
                    "Apologize, tell the caller it was not approved, and offer another option."
                )

            now = time.monotonic()
            if now - last_reassured >= REASSURE_EVERY_S:
                ctx.session.say("Still with you — I'm just waiting on that approval.")
                last_reassured = now
            await asyncio.sleep(POLL_INTERVAL_S)

        return (
            "PENDING: no supervisor has responded yet. Tell the caller it is still under "
            "review and that they will be updated by email. Do NOT say it was approved."
        )
