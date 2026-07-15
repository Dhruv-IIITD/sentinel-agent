"""A one-call audio→VAD→STT trace, so a broken call tells us *where* it broke.

The failure we keep hitting — agent greets you, then hears nothing — has three very
different causes that all *look* identical from the browser. This taps each stage on
the worker side and logs a ladder:

    🔊 mic audio   — is the caller's track carrying sound AT ALL? (server-side truth,
                     independent of any browser meter). SILENT here = a dead input
                     device; nothing downstream can fire.
    🎤 VAD         — did voice-activity detection decide the caller is speaking?
                     Audio LOUD but no VAD = a VAD threshold / format problem.
    📝 STT         — did Deepgram return a transcript? VAD fired but no STT = the STT
                     socket (key, model, network).
    🤖 AGENT       — did the agent move to thinking/speaking? STT text but no agent =
                     turn-taking / LLM.

Read the log top-down: the last rung that fires is the stage that works; the next one
is where it breaks. Enabled by default; set VOICE_DIAG=false to silence.
"""

from __future__ import annotations

import asyncio
import logging
import time
from array import array

from livekit import rtc

logger = logging.getLogger("voice-diag")

# int16 peak is 32767; divide by 327 to get a rough 0–100 level.
_SILENT = 30      # below this = effectively no signal
_QUIET = 800      # below this = present but faint


def _label(peak: int) -> str:
    if peak < _SILENT:
        return "SILENT ⚠️  (device sending no sound)"
    if peak < _QUIET:
        return "quiet"
    return "LOUD ✅"


async def _energy_probe(track: rtc.Track, who: str) -> None:
    """Log the caller's mic level every ~2s of audio. Peak amplitude, not RMS — we only
    need 'is there sound', and min/max on the sample array is C-fast (no per-sample loop)."""
    stream = rtc.AudioStream(track, sample_rate=16000, num_channels=1)
    window = time.monotonic()
    frames = 0
    peak = 0
    try:
        async for event in stream:
            data = array("h")
            data.frombytes(bytes(event.frame.data))
            if len(data):
                peak = max(peak, max(data), -min(data))
            frames += 1
            if time.monotonic() - window >= 2.0:
                level = min(100, peak // 327)
                logger.info("🔊 mic audio from %s: %d frames · peak %d/100 · %s",
                            who, frames, level, _label(peak))
                window, frames, peak = time.monotonic(), 0, 0
    except Exception as exc:  # noqa: BLE001
        logger.debug("energy probe ended: %s", exc)
    finally:
        await stream.aclose()


def attach_diagnostics(session, ctx) -> None:
    logger.info(
        "── voice diagnostics ON ── speak and watch the ladder: 🔊 audio → 🎤 VAD → 📝 STT → 🤖 agent"
    )

    @session.on("user_state_changed")
    def _on_user_state(ev) -> None:  # noqa: ANN001
        # → "speaking" is VAD deciding the caller started talking.
        arrow = "▶ heard speech" if ev.new_state == "speaking" else ""
        logger.info("🎤 VAD  user: %s → %s   %s", ev.old_state, ev.new_state, arrow)

    @session.on("user_input_transcribed")
    def _on_transcribed(ev) -> None:  # noqa: ANN001
        kind = "FINAL " if ev.is_final else "interim"
        logger.info("📝 STT  [%s]: %r", kind, ev.transcript)

    @session.on("agent_state_changed")
    def _on_agent_state(ev) -> None:  # noqa: ANN001
        logger.info("🤖 AGENT: %s → %s", ev.old_state, ev.new_state)

    @ctx.room.on("track_subscribed")
    def _on_track(track, publication, participant) -> None:  # noqa: ANN001
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            logger.info("🔊 subscribed to mic from %s (source=%s) — probing energy",
                        participant.identity, publication.source)
            asyncio.create_task(_energy_probe(track, participant.identity))
