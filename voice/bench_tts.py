"""TTS A/B latency benchmark — Deepgram Aura vs Sarvam.

Synthesizes the same support-style sentences with both engines and reports
time-to-first-byte (TTFB — the number that drives perceived latency) and the
real-time factor (RTF). Needs DEEPGRAM_API_KEY and SARVAM_API_KEY in voice/.env.

    python voice/bench_tts.py

Note: Sarvam's English is Indian English (en-IN); Deepgram Aura is US English.
So this measures both *latency* and, by ear, *accent fit* for your audience.
"""

from __future__ import annotations

import asyncio
import statistics
import time

import aiohttp

from tts import build_tts

SENTENCES = [
    "Sure, I can help you with that.",
    "Your order 4471 shipped yesterday and should arrive on Thursday.",
    "That refund needs a quick supervisor approval, I can hold for a moment.",
    "Okay, I've issued your one hundred eighty dollar refund; you'll see it in three to five business days.",
    "Is there anything else I can help you with today?",
]


async def _synth(tts, text: str) -> tuple[float, float, float]:
    """Return (ttfb_s, total_s, audio_s) for one synthesis."""
    stream = tts.synthesize(text)
    t0 = time.perf_counter()
    ttfb: float | None = None
    audio_s = 0.0
    try:
        async for ev in stream:
            if ttfb is None:
                ttfb = time.perf_counter() - t0
            frame = ev.frame
            audio_s += frame.samples_per_channel / frame.sample_rate
    finally:
        aclose = getattr(stream, "aclose", None)
        if aclose:
            await aclose()
    total = time.perf_counter() - t0
    return (ttfb if ttfb is not None else total, total, audio_s)


async def _bench(provider: str, http: aiohttp.ClientSession) -> None:
    print(f"\n=== {provider} ===")
    tts = build_tts(provider, http_session=http)
    try:
        await _synth(tts, "Hello there.")  # warmup (connection setup; not measured)
    except Exception as e:  # noqa: BLE001
        print(f"[{provider}] FAILED: {e}")
        return

    ttfbs: list[float] = []
    rtfs: list[float] = []
    for s in SENTENCES:
        ttfb, total, audio_s = await _synth(tts, s)
        rtf = total / audio_s if audio_s else float("nan")
        ttfbs.append(ttfb)
        rtfs.append(rtf)
        print(
            f"[{provider}] TTFB {ttfb * 1000:6.0f} ms | synth {total * 1000:6.0f} ms | "
            f"audio {audio_s:4.1f}s | RTF {rtf:.2f} | {s[:38]}"
        )

    print(
        f"[{provider}] --> TTFB median {statistics.median(ttfbs) * 1000:.0f} ms, "
        f"max {max(ttfbs) * 1000:.0f} ms | mean RTF {statistics.mean(rtfs):.2f}"
    )
    aclose = getattr(tts, "aclose", None)
    if aclose:
        await aclose()


async def main() -> None:
    async with aiohttp.ClientSession() as http:
        for provider in ("deepgram", "sarvam"):
            await _bench(provider, http)
    print("\nLower TTFB = snappier first word. RTF < 1 means synthesis outpaces playback.")


if __name__ == "__main__":
    asyncio.run(main())
