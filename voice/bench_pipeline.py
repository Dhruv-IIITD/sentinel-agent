"""Pipeline benchmark — the latency budget, and what the STT tuning is actually worth.

    python voice/bench_pipeline.py        # needs DEEPGRAM_API_KEY + GROQ_API_KEY (+ a TTS key)

Two questions, measured rather than argued:

**1. Word error rate, boosted vs control.** We speak a domain sentence with the TTS,
feed that audio straight back into Deepgram, and compare the transcript to what we
said. Running it twice — once with `numerals` + `keyterm` boosting on, once off —
prices the tuning in `stt.py`. The interesting column is not the average WER, it is
whether **the order number survived**: "4471" heard as "four four seven one" is a tool
call the agent has to guess at, and a guessed digit is a refund against the wrong order.

**2. The latency budget.** Time-to-first-token for the LLM, time-to-first-byte for the
TTS, and STT turnaround — the three terms that decide whether the agent feels like a
person or a kiosk. Target: end-of-speech to first audio in ~700ms-1.2s.

This is a round-trip *proxy*, not a microphone: TTS audio is cleaner than a phone line,
so real-world WER will be worse. It measures the tuning delta and the latency shape,
which is what it is for.
"""

from __future__ import annotations

import asyncio
import re
import statistics
import time

import aiohttp
from livekit import rtc

from config import settings
from stt import build_stt
from tts import build_tts

# Domain sentences: order numbers, product names, the words that actually matter.
SENTENCES = [
    "I want a refund on order 4471, the ceramic dinner set arrived damaged.",
    "Can you track order 4473, the standing desk?",
    "Please cancel order 4472 and give me store credit instead.",
    "My shipping address changed, order 4471 should go to 12 Oak Street.",
    "The Bluetooth speaker was defective, I would like a refund of 39 dollars.",
]

_PUNCT = re.compile(r"[^\w\s]")


def _norm(s: str) -> list[str]:
    return _PUNCT.sub(" ", s.lower()).split()


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate — Levenshtein distance over words, normalised by reference length."""
    r, h = _norm(reference), _norm(hypothesis)
    if not r:
        return 0.0
    prev = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        cur = [i] + [0] * len(h)
        for j in range(1, len(h) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r[i - 1] != h[j - 1]))
        prev = cur
    return prev[len(h)] / len(r)


def order_numbers(s: str) -> set[str]:
    return set(re.findall(r"\b\d{4}\b", s))


async def synthesize(tts, text: str) -> tuple[list[rtc.AudioFrame], float]:
    """Speak a sentence; return the audio and the time to the first byte of it."""
    stream = tts.synthesize(text)
    t0 = time.perf_counter()
    ttfb, frames = None, []
    try:
        async for ev in stream:
            if ttfb is None:
                ttfb = time.perf_counter() - t0
            frames.append(ev.frame)
    finally:
        close = getattr(stream, "aclose", None)
        if close:
            await close()
    return frames, ttfb or 0.0


async def transcribe(stt, frames: list[rtc.AudioFrame]) -> tuple[str, float]:
    t0 = time.perf_counter()
    event = await stt.recognize(frames)
    elapsed = time.perf_counter() - t0
    text = event.alternatives[0].text if event.alternatives else ""
    return text, elapsed


async def llm_ttft(http: aiohttp.ClientSession, prompt: str) -> float:
    """Time to first token from Groq, with the agent's real system prompt."""
    from support_agent import INSTRUCTIONS

    t0 = time.perf_counter()
    async with http.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
        json={
            "model": settings.groq_model,
            "messages": [
                {"role": "system", "content": INSTRUCTIONS},
                {"role": "user", "content": prompt},
            ],
            "stream": True,
            "max_completion_tokens": 60,
        },
    ) as resp:
        resp.raise_for_status()
        async for raw in resp.content:
            line = raw.decode().strip()
            if line.startswith("data:") and "content" in line:
                return time.perf_counter() - t0
    return time.perf_counter() - t0


async def stt_arm(http: aiohttp.ClientSession, audio: list, boosted: bool) -> dict:
    stt = build_stt(http_session=http, boosted=boosted)
    wers, lats, kept = [], [], 0
    total_orders = 0
    for text, frames in audio:
        hyp, elapsed = await transcribe(stt, frames)
        wers.append(wer(text, hyp))
        lats.append(elapsed)
        want = order_numbers(text)
        total_orders += len(want)
        kept += len(want & order_numbers(hyp))
    close = getattr(stt, "aclose", None)
    if close:
        await close()
    return {
        "wer": statistics.mean(wers),
        "latency": statistics.median(lats),
        "orders_kept": kept,
        "orders_total": total_orders,
    }


async def main() -> None:
    async with aiohttp.ClientSession() as http:
        tts = build_tts(http_session=http)
        print(f"\nTTS={settings.tts_provider}  STT={settings.stt_model}  LLM={settings.groq_model}\n")

        # --- speak every sentence once; reuse the audio for both STT arms ---
        await synthesize(tts, "warm up.")
        audio, ttfbs = [], []
        for s in SENTENCES:
            frames, ttfb = await synthesize(tts, s)
            audio.append((s, frames))
            ttfbs.append(ttfb)

        boosted = await stt_arm(http, audio, boosted=True)
        control = await stt_arm(http, audio, boosted=False)

        await llm_ttft(http, "warm up")
        ttfts = [await llm_ttft(http, s) for s in SENTENCES]

    print("  Accuracy — what the STT tuning buys")
    print("  " + "-" * 58)
    print(f"  {'':<22} {'word error':>12} {'order numbers kept':>20}")
    print(f"  {'boosted (shipped)':<22} {boosted['wer'] * 100:>11.1f}% "
          f"{boosted['orders_kept']}/{boosted['orders_total']:>18}")
    print(f"  {'control (no tuning)':<22} {control['wer'] * 100:>11.1f}% "
          f"{control['orders_kept']}/{control['orders_total']:>18}")
    delta = (control["wer"] - boosted["wer"]) * 100
    print(f"  {'delta':<22} {delta:>11.1f}pp\n")

    p50 = statistics.median
    print("  Latency budget (end of speech -> first audio)")
    print("  " + "-" * 58)
    rows = [
        ("STT finalise", p50([boosted["latency"]])),
        ("LLM first token (Groq)", p50(ttfts)),
        ("TTS first byte", p50(ttfbs)),
    ]
    for label, seconds in rows:
        print(f"  {label:<26} {seconds * 1000:>7.0f} ms")
    total = sum(s for _, s in rows)
    print(f"  {'':<26} {'-' * 10}")
    print(f"  {'serial total':<26} {total * 1000:>7.0f} ms")
    print("\n  Note: the live pipeline overlaps these — TTS starts on the LLM's first")
    print("  sentence rather than waiting for the last token — so the felt latency is")
    print("  lower than the serial sum. Target is 700-1200 ms.\n")


if __name__ == "__main__":
    asyncio.run(main())
