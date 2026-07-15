"""The approval call — the agent phones a human to get sign-off.

This is the human-in-the-loop made audible. When policy gates an action, the backend
dispatches this agent into a room (`POST /voice/approval-call/{id}`). It reads the
approval id from the job metadata, briefs whoever picks up, takes a spoken decision,
and submits it — which resumes the paused graph through the *same* decision endpoint
the dashboard uses. With a SIP trunk it rings a real phone; without one the same call
happens in a browser room.

Two deliberate choices:

* **The briefing is spoken verbatim, not generated.** `session.say()` reads a scripted
  line built from the approval row, so the amount, the order, and the policy clause a
  human is asked to approve are exactly what is in the queue — an LLM cannot paraphrase
  a refund into the wrong number. Only the conversation *after* the briefing is modelled.
* **A spoken PIN gates the decision.** Whoever answers the phone could otherwise approve
  a refund. `submit_decision` refuses until `verify_approver` succeeds — enforced in the
  tool layer, not the prompt, exactly like the caller identity gate.

Run it as its own worker (an explicit `agent_name` means it is dispatched on demand,
never into every room):

    python voice/approver_agent.py dev
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    RoomInputOptions,
    RunContext,
    WorkerOptions,
    cli,
    function_tool,
    get_job_context,
)
from livekit.plugins import groq, silero

from backend import Backend
from config import preflight, settings
from stt import build_stt, turn_detection
from tts import build_tts

logger = logging.getLogger("approver-agent")

_MARKDOWN = re.compile(r"\*\*|__|[*`]")
# classify_risk appends the retrieved clause as "... [policy: <clause>]". That tail is
# for the dashboard, not for a phone call: read aloud it becomes literal brackets, and
# the clause is often not the one that actually triggered the gate. Keep the reason.
_POLICY_TAIL = re.compile(r"\s*\[policy:.*\]\s*$", re.S)
HANGUP_AFTER_S = 7.0  # let the closing line finish playing before we tear the room down

INSTRUCTIONS = (
    "You are calling a human supervisor to get approval for an action an AI support agent "
    "wants to take. You are on a phone call: be brief and clear, one or two short sentences.\n\n"
    "You have ALREADY read out the action and the policy — do not repeat it unless asked.\n\n"
    "PIN: if the caller is asked for an approval PIN, pass whatever digits they say to "
    "verify_approver. Never reveal or guess the PIN.\n\n"
    "DECISION: when the supervisor clearly approves or declines, call submit_decision "
    "(approve=true to approve, approve=false to decline). If they are unclear or want more "
    "detail, answer their question and ask again — do not guess. Never record a decision "
    "they did not clearly give. After it is recorded, confirm in one sentence and say goodbye."
)


@dataclass
class ApprovalCallState:
    backend: Backend
    approval: dict
    pin_required: bool
    verified: bool = False
    submitted: bool = False


def _speakable(text: str) -> str:
    return _MARKDOWN.sub("", text).strip()


def _describe(tool: str, args: dict) -> str:
    """A spoken description of the action, built from the approval row itself."""
    order = args.get("order_id")
    if tool == "issue_refund":
        return f"a refund of {float(args.get('amount', 0)):,.0f} dollars on order {order}"
    if tool == "cancel_order":
        return f"cancelling order {order}"
    if tool == "apply_credit":
        return f"{float(args.get('amount', 0)):,.0f} dollars of store credit for customer {args.get('customer_id')}"
    if tool == "update_address":
        return f"changing the shipping address on order {order}"
    return f"the action {tool.replace('_', ' ')}"


def _reason_for_speech(citation: str) -> str:
    reason = _POLICY_TAIL.sub("", _speakable(citation))
    return reason.replace("_", " ").strip(" .")


def briefing(approval: dict, pin_required: bool) -> str:
    action = _describe(approval["tool_name"], approval.get("tool_args") or {})
    line = f"Hello, this is the support agent. I need your approval for {action}. "
    reason = _reason_for_speech(approval.get("policy_citation") or "")
    if reason:
        line += f"The reason it needs you: {reason}. "
    line += (
        "Please say your approval PIN, and then tell me whether you approve."
        if pin_required
        else "Do you approve?"
    )
    return line


class ApproverAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=INSTRUCTIONS)

    @function_tool
    async def verify_approver(self, ctx: RunContext[ApprovalCallState], pin: str) -> str:
        """Check the approval PIN the supervisor said out loud. Must succeed before any
        decision can be recorded."""
        state = ctx.userdata
        if not state.pin_required:
            state.verified = True
            return "No PIN is required. You may record the decision."

        spoken = re.sub(r"\D", "", pin)  # "two four six eight" -> STT digits; strip spaces/dashes
        if spoken and spoken == re.sub(r"\D", "", settings.approver_pin):
            state.verified = True
            return "PIN accepted. You may now record their decision."
        return "That PIN is not correct. Ask them to try again. Do NOT record any decision."

    @function_tool
    async def submit_decision(
        self, ctx: RunContext[ApprovalCallState], approve: bool, reason: str = ""
    ) -> str:
        """Record the supervisor's decision on the pending action. Set approve=true to
        approve it, approve=false to decline. Only call this when they have clearly said so."""
        state = ctx.userdata
        if state.pin_required and not state.verified:
            return "NOT_VERIFIED: ask for the approval PIN first and call verify_approver."
        if state.submitted:
            return "That decision has already been recorded."

        decision = "approve" if approve else "reject"
        await state.backend.submit_decision(
            state.approval["id"], decision, reason or "decided on an approval call"
        )
        state.submitted = True
        logger.info("approval %s %sd by phone", state.approval["id"], decision)

        # Hang up once the closing line has played.
        async def _hangup() -> None:
            await asyncio.sleep(HANGUP_AFTER_S)
            try:
                await get_job_context().delete_room()
            except Exception:  # noqa: BLE001 - the room may already be gone
                logger.debug("room already closed")

        asyncio.create_task(_hangup())

        verb = "approved" if approve else "declined"
        return f"Recorded — the action was {verb}. Thank them briefly and say goodbye."


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext) -> None:
    metadata = json.loads(ctx.job.metadata or "{}")
    approval_id = metadata.get("approval_id")

    backend = Backend(settings.backend_url)
    ctx.add_shutdown_callback(backend.aclose)

    approval = await backend.get_approval(approval_id) if approval_id else None
    if approval is None:
        logger.error("no approval found for job metadata %r — nothing to decide", metadata)
        ctx.shutdown()
        return
    if approval["status"] != "pending":
        logger.info("approval %s is already %s — hanging up", approval_id, approval["status"])
        ctx.shutdown()
        return

    await ctx.connect()

    pin_required = bool(settings.approver_pin)
    if not pin_required:
        logger.warning("APPROVER_PIN is unset — anyone who answers this call can approve")

    session: AgentSession[ApprovalCallState] = AgentSession[ApprovalCallState](
        userdata=ApprovalCallState(backend=backend, approval=approval, pin_required=pin_required),
        vad=ctx.proc.userdata["vad"],
        stt=build_stt(),
        llm=groq.LLM(model=settings.groq_model, api_key=settings.groq_api_key or None),
        tts=build_tts(),
        turn_handling={
            "turn_detection": turn_detection(),
            "endpointing": {
                "min_delay": settings.min_endpointing_delay,
                "max_delay": settings.max_endpointing_delay,
            },
            "interruption": {
                "enabled": True,
                "min_duration": settings.min_interruption_duration,
                "min_words": settings.min_interruption_words,
            },
            "preemptive_generation": {"enabled": settings.preemptive_generation},
        },
    )
    await session.start(ApproverAgent(), room=ctx.room, room_input_options=RoomInputOptions())

    # Don't brief an empty room — wait for the phone to actually be answered.
    await ctx.wait_for_participant()
    session.say(briefing(approval, pin_required))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    preflight()  # fail at boot, not on the first caller
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            # An explicit agent_name = dispatched on demand only, never into every room.
            agent_name=settings.approver_agent_name,
        )
    )
