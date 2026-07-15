"""Speech-to-text factory — tuned for this domain.

Two settings do most of the accuracy work on a support call:

* **`numerals=True`.** Deepgram then writes spoken numbers as digits, so "order four
  four seven one" arrives as `order 4471`. This is not cosmetic: without it the model
  has to reconstruct the order number from words before calling a tool, and one wrong
  digit is a refund issued against **someone else's order**. It is the cheapest
  correctness win in the whole pipeline.
* **`keyterm` boosting.** The vocabulary this domain actually uses — "refund",
  "damaged", "store credit", the product names. Rare and product-specific words are
  exactly the ones a general STT model drops or mangles.

`bench_pipeline.py` measures what these are worth (word error rate, boosted vs not),
which is why `boosted=False` exists — it is the control arm of that experiment.
"""

from __future__ import annotations

import logging

import aiohttp
from livekit.agents.stt import STT
from livekit.plugins import deepgram

from config import Settings, settings

logger = logging.getLogger("voice-stt")


def turn_detection():
    """How we decide the caller has finished speaking.

    VAD ends a turn on *silence*, so it must wait out a pause — and it will happily cut
    someone off mid-sentence when they pause to think. Semantic detection ends the turn
    on *meaning*, which both cuts perceived latency and stops the agent interrupting.

    It runs on LiveKit's inference service (so it needs LiveKit credentials). If it can't
    be constructed we fall back to VAD rather than failing the call. Default is `vad`
    because it is the one we can guarantee works out of the box; `TURN_DETECTION=semantic`
    is the recommended upgrade once you have LiveKit credentials in place.
    """
    if settings.turn_detection != "semantic":
        return "vad"
    try:
        from livekit.agents import inference

        return inference.TurnDetector()
    except Exception as exc:  # noqa: BLE001
        logger.warning("semantic turn detection unavailable (%s) — falling back to VAD", exc)
        return "vad"


def build_stt(
    *,
    cfg: Settings = settings,
    http_session: aiohttp.ClientSession | None = None,
    boosted: bool = True,
) -> STT:
    kwargs: dict = {
        "model": cfg.stt_model,
        "language": cfg.stt_language,
        "api_key": cfg.deepgram_api_key or None,
        "endpointing_ms": cfg.stt_endpointing_ms,
        "numerals": cfg.stt_numerals and boosted,
        "http_session": http_session,
    }
    if boosted and cfg.stt_keyterms:
        kwargs["keyterm"] = list(cfg.stt_keyterms)
    return deepgram.STT(**kwargs)
