"""Pluggable TTS factory — the Deepgram-vs-Sarvam A/B switch.

Both providers ship first-class LiveKit plugins, so swapping them is one line,
driven by TTS_PROVIDER (or an explicit argument, used by the benchmark).
"""

from __future__ import annotations

import aiohttp
from livekit.agents.tts import TTS
from livekit.plugins import deepgram, sarvam

from config import Settings, settings


def build_tts(
    provider: str | None = None,
    *,
    cfg: Settings = settings,
    http_session: aiohttp.ClientSession | None = None,
) -> TTS:
    """Return a configured LiveKit TTS for `provider` ("deepgram" | "sarvam").

    Pass `http_session` when constructing outside a LiveKit worker (e.g. the
    benchmark); inside the worker leave it None and the job context provides one.
    """
    provider = (provider or cfg.tts_provider).lower()

    if provider == "deepgram":
        return deepgram.TTS(
            model=cfg.deepgram_tts_model,
            api_key=cfg.deepgram_api_key or None,
            http_session=http_session,
        )
    if provider == "sarvam":
        return sarvam.TTS(
            target_language_code=cfg.sarvam_tts_language,
            model=cfg.sarvam_model,
            speaker=cfg.sarvam_speaker or None,
            api_key=cfg.sarvam_api_key or None,
            http_session=http_session,
        )
    raise ValueError(f"unknown TTS provider {provider!r} (use 'deepgram' or 'sarvam')")
