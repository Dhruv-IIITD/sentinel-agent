"""Voice worker configuration.

Standalone from the backend's config — this service only needs the voice/LLM
provider keys and a few latency knobs. Values come from voice/.env.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, ""))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, ""))
    except ValueError:
        return default


def _csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())


# The words this domain lives on. A general STT model happily mangles product names
# and drops "store credit"; boosting them is nearly free.
DEFAULT_KEYTERMS: tuple[str, ...] = (
    "refund",
    "order number",
    "cancel",
    "damaged",
    "defective",
    "store credit",
    "shipping address",
    "tracking",
    "supervisor",
    "ceramic dinner set",
    "Bluetooth speaker",
    "standing desk",
)


@dataclass(frozen=True)
class Settings:
    # LiveKit (the SDK also reads these straight from the environment)
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    # Provider keys
    deepgram_api_key: str
    groq_api_key: str
    sarvam_api_key: str
    # The HITL backend the voice tools call (FastAPI; `make run`)
    backend_url: str
    # Spoken PIN that gates an approval given over the phone. Whoever answers the
    # call would otherwise be able to approve a refund. Empty = no PIN (dev only).
    approver_pin: str
    # Must match the backend's APPROVER_AGENT_NAME — it is the dispatch address.
    approver_agent_name: str
    # Per-call audio→VAD→STT trace in the worker log (see diagnostics.py).
    diag: bool
    # Which TTS to use — the A/B switch: "deepgram" | "sarvam"
    tts_provider: str
    # STT (Deepgram Nova-3)
    stt_model: str
    stt_language: str
    # Write spoken numbers as digits ("four four seven one" -> 4471). See stt.py.
    stt_numerals: bool
    # Domain vocabulary to boost — the words a general model drops.
    stt_keyterms: tuple[str, ...]
    # How long Deepgram waits on silence before finalising. Lower = snappier turns.
    stt_endpointing_ms: int
    # "vad" (silence-based) or "semantic" (ends the turn on meaning — lower perceived
    # latency and far fewer mid-sentence interruptions, but needs a model download:
    # `python voice/agent.py download-files`). Falls back to vad if unavailable.
    turn_detection: str
    # LLM (Groq)
    groq_model: str
    # Deepgram Aura TTS
    deepgram_tts_model: str
    # Sarvam TTS (note: Sarvam's English is Indian English, en-IN)
    sarvam_model: str
    sarvam_tts_language: str
    sarvam_speaker: str
    # Latency tuning
    min_endpointing_delay: float
    max_endpointing_delay: float
    preemptive_generation: bool
    # Barge-in: how much speech it takes to cut the agent off. Raising min_words stops a
    # cough or an "mm-hm" from killing its sentence, at the cost of a slower true interrupt.
    min_interruption_duration: float
    min_interruption_words: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            livekit_url=os.getenv("LIVEKIT_URL", ""),
            livekit_api_key=os.getenv("LIVEKIT_API_KEY", ""),
            livekit_api_secret=os.getenv("LIVEKIT_API_SECRET", ""),
            deepgram_api_key=os.getenv("DEEPGRAM_API_KEY", ""),
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            sarvam_api_key=os.getenv("SARVAM_API_KEY", ""),
            backend_url=os.getenv("BACKEND_URL", "http://localhost:8000"),
            approver_pin=os.getenv("APPROVER_PIN", ""),
            approver_agent_name=os.getenv("APPROVER_AGENT_NAME", "approval-agent"),
            diag=_bool("VOICE_DIAG", True),
            tts_provider=os.getenv("TTS_PROVIDER", "deepgram").lower(),
            stt_model=os.getenv("STT_MODEL", "nova-3"),
            stt_language=os.getenv("STT_LANGUAGE", "en-US"),
            stt_numerals=_bool("STT_NUMERALS", True),
            stt_keyterms=_csv("STT_KEYTERMS", DEFAULT_KEYTERMS),
            stt_endpointing_ms=_int("STT_ENDPOINTING_MS", 25),
            turn_detection=os.getenv("TURN_DETECTION", "vad").lower(),
            groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            deepgram_tts_model=os.getenv("DEEPGRAM_TTS_MODEL", "aura-2-andromeda-en"),
            sarvam_model=os.getenv("SARVAM_MODEL", "bulbul:v3"),
            sarvam_tts_language=os.getenv("SARVAM_TTS_LANGUAGE", "en-IN"),
            sarvam_speaker=os.getenv("SARVAM_SPEAKER", "amelia"),
            min_endpointing_delay=_float("MIN_ENDPOINTING_DELAY", 0.4),
            max_endpointing_delay=_float("MAX_ENDPOINTING_DELAY", 3.0),
            preemptive_generation=_bool("PREEMPTIVE_GENERATION", True),
            min_interruption_duration=_float("MIN_INTERRUPTION_DURATION", 0.5),
            min_interruption_words=_int("MIN_INTERRUPTION_WORDS", 0),
        )


settings = Settings.from_env()


def missing_keys(cfg: Settings = settings) -> list[str]:
    """Provider keys this worker cannot run a single call without."""
    missing = []
    if not cfg.deepgram_api_key:
        missing.append("DEEPGRAM_API_KEY  — speech-to-text (and TTS, on TTS_PROVIDER=deepgram)")
    if not cfg.groq_api_key:
        missing.append("GROQ_API_KEY      — the agent's reasoning")
    if cfg.tts_provider == "sarvam" and not cfg.sarvam_api_key:
        missing.append("SARVAM_API_KEY    — text-to-speech (TTS_PROVIDER=sarvam)")
    return missing


def preflight() -> None:
    """Refuse to start without the keys, instead of crashing on the first call.

    A LiveKit worker builds its STT/LLM/TTS *inside the job*, so a missing key does not
    surface until someone is already on the line — the worker looks healthy, accepts the
    call, and only then dies. On a support line that is a dropped customer. Fail at boot
    instead: loud, early, and with the fix in the message.
    """
    missing = missing_keys()
    if not missing:
        return
    print("\n  Cannot start: missing provider keys in voice/.env\n", file=sys.stderr)
    for item in missing:
        print(f"    ✗ {item}", file=sys.stderr)
    print(
        "\n  Add them to voice/.env (see voice/.env.example), then start the worker again."
        "\n  Deepgram keys: https://console.deepgram.com\n",
        file=sys.stderr,
    )
    raise SystemExit(1)
