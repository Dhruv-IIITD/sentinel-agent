"""LiveKit voice worker — Phase 2: grounded read-only tools + identity gate.

Deepgram Nova-3 (STT) -> Groq llama-3.3-70b (LLM) -> pluggable TTS (Deepgram Aura
or Sarvam). The agent's tools are thin RPCs to the backend (see support_agent.py);
the LangGraph risk gate stays out of the conversational hot path (Pattern A in
docs/VOICE_PLAN.md).

Run (the backend must be up — `make run` — for the tools to work):
    python voice/agent.py console   # talk in your terminal (no frontend, no LiveKit Cloud)
    python voice/agent.py dev       # LiveKit worker; join via the Agents Playground
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from livekit.agents import (
    AgentSession,
    JobContext,
    JobProcess,
    ConversationItemAddedEvent,
    RoomInputOptions,
    WorkerOptions,
    cli,
)
from livekit.plugins import groq, silero

from backend import Backend
from config import preflight, settings
from diagnostics import attach_diagnostics
from stt import build_stt, turn_detection
from support_agent import CallState, SupportAgent
from tts import build_tts

logger = logging.getLogger("voice-agent")


def prewarm(proc: JobProcess) -> None:
    # Load the VAD once per worker process (not once per call) to keep latency low.
    proc.userdata["vad"] = silero.VAD.load()


def latency_payload(eou: float, report: dict) -> str:
    """One turn's latency, taken from LiveKit's own per-message metrics.

    `e2e_latency` is the authoritative number — *"time from when the user finished
    speaking to when the agent began responding"*, measured by the framework. We do not
    recompute it by summing the legs: a turn that calls a tool runs the model twice, and
    any hand-rolled sum quietly drifts from what the caller actually heard.

    The legs are shown underneath to say *where the time went*, and whatever they do not
    account for is reported honestly as `other` rather than being hidden:

        end_of_turn_delay  — deciding the caller finished   (turn detection)
        llm_node_ttft      — first token of the reply        (Groq)
        tts_node_ttfb      — first byte of audio             (Deepgram/Sarvam)
        other              — the remainder, so the bar sums to e2e

    Tool execution is not in here. A turn that pauses for human approval is not a latency
    problem — it is the product. Tool time is measured separately (`GET /metrics`).
    """
    ms = lambda s: round((s or 0) * 1000)  # noqa: E731
    e2e = report.get("e2e_latency") or 0.0
    llm = report.get("llm_node_ttft") or 0.0
    tts = report.get("tts_node_ttfb") or 0.0
    return json.dumps({
        "stt_ms": ms(eou),
        "llm_ms": ms(llm),
        "tts_ms": ms(tts),
        "other_ms": max(0, ms(e2e) - ms(eou) - ms(llm) - ms(tts)),
        "total_ms": ms(e2e),
    })


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

    backend = Backend(settings.backend_url)
    ctx.add_shutdown_callback(backend.aclose)

    # One graph thread per call: actions taken on this call are checkpointed under
    # it, so the dashboard (and a resume after a restart) can find them.
    room_name = getattr(ctx.room, "name", "") or uuid.uuid4().hex
    thread_id = f"voice-{room_name}"
    logger.info("call thread_id=%s", thread_id)

    session: AgentSession[CallState] = AgentSession[CallState](
        userdata=CallState(backend=backend, thread_id=thread_id),
        vad=ctx.proc.userdata["vad"],
        stt=build_stt(),
        llm=groq.LLM(
            model=settings.groq_model,
            api_key=settings.groq_api_key or None,
        ),
        tts=build_tts(),
        # Turn-taking and the latency levers, in one place. (The old top-level
        # min_endpointing_delay / preemptive_generation kwargs are deprecated — they
        # still work, but only via a migration shim that logs a warning.)
        turn_handling={
            "turn_detection": turn_detection(),
            "endpointing": {
                # How long a silence must last before we call the caller's turn over.
                # The single biggest lever on felt latency: too low and we cut people
                # off mid-thought, too high and every reply feels laggy.
                "min_delay": settings.min_endpointing_delay,
                "max_delay": settings.max_endpointing_delay,
            },
            "interruption": {
                # Barge-in: the caller can talk over the agent and it stops immediately.
                "enabled": True,
                "min_duration": settings.min_interruption_duration,
                # A stray cough or "mm-hm" must not kill the agent's sentence.
                "min_words": settings.min_interruption_words,
            },
            "preemptive_generation": {"enabled": settings.preemptive_generation},
        },
    )

    # Per-turn latency, streamed to the console so it can be read beside the transcript
    # rather than dug out of the worker's log. Sourced from `conversation_item_added`
    # (the `metrics_collected` event is deprecated), where LiveKit attaches a metrics
    # report to each message: turn-detection cost lands on the *user's* message, and the
    # LLM/TTS/e2e figures on the *assistant's* reply — so we carry the former across.
    pending: dict[str, float] = {}

    async def _publish(data: str) -> None:
        try:
            await ctx.room.local_participant.publish_data(data, topic="latency", reliable=True)
        except Exception as exc:  # noqa: BLE001 - telemetry must never kill a call
            logger.debug("could not publish latency: %s", exc)

    @session.on("conversation_item_added")
    def _on_item(ev: ConversationItemAddedEvent) -> None:
        item = ev.item
        report = getattr(item, "metrics", None) or {}
        role = getattr(item, "role", None)

        if role == "user":
            pending["eou"] = report.get("end_of_turn_delay") or 0.0
            return
        if role != "assistant" or not report.get("e2e_latency"):
            return

        data = latency_payload(pending.pop("eou", 0.0), report)
        logger.info("turn latency %s", data)
        asyncio.create_task(_publish(data))

    # The audio→VAD→STT trace. Attach BEFORE start() so its track_subscribed handler
    # catches the caller's mic when it arrives.
    if settings.diag:
        attach_diagnostics(session, ctx)

    await session.start(
        SupportAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(),
    )
    await session.generate_reply(
        instructions=(
            "Greet the caller warmly in one short sentence, mention you can help with "
            "orders, shipments, and refunds, and ask how you can help."
        )
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    preflight()  # fail at boot, not on the first caller
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
