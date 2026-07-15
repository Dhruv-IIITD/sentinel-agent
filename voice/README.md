# Voice worker (Phase 1)

The real-time voice front-end for the HITL agent: **Deepgram Nova-3** (STT) →
**Groq llama-3.3-70b** (LLM) → **pluggable TTS** (Deepgram Aura *or* Sarvam).
Runs as a separate service from the backend, with its own venv.

**Phases 2 & 3 are in:** the agent verifies the caller, answers questions grounded in
the backend, and **takes real actions with a human in the loop** — pausing mid-call
for approval and resuming after the decision. See
[`docs/VOICE_PLAN.md`](../docs/VOICE_PLAN.md) for the full arc.

## What it can do

| Tool | Verification | Gate |
|---|---|---|
| `verify_identity` (order number + email or name) | — | — |
| `get_order_status` · `track_shipment` | ✅ per-order | read |
| `check_refund_eligibility` (read-only; runs the real policy gate) | ✅ per-order | read |
| `get_refund_policy` | no (public) | read |
| `update_shipping_address` | ✅ per-order | reversible → immediate |
| `issue_refund` | ✅ per-order | **policy decides** at runtime |
| `cancel_order` | ✅ per-order | **always needs a human** |

Two things are enforced in code, not in the prompt:

* **The identity gate** — an order tool hard-refuses until `verify_identity` succeeds
  for *that order* in *this call*. A jailbroken prompt can't talk past it.
* **Actions never execute in the voice worker.** They post to the backend, which runs
  them through the *real* LangGraph risk gate. If policy gates it, the graph pauses
  (checkpointed), the caller is put on hold, and a human decides in the same dashboard
  a chat-initiated approval would land in. The agent may never claim success on its
  own — tools return an explicit DONE / APPROVED / DECLINED / PENDING verdict.

## Setup

```bash
uv venv voice/.venv --python 3.12
uv pip install --python voice/.venv -r voice/requirements.txt
cp voice/.env.example voice/.env      # then fill in your keys
```

## 0. Measure it (latency + accuracy)

```bash
voice/.venv/bin/python voice/bench_pipeline.py   # WER (tuned vs not) + the latency budget
```

Speaks a domain sentence, feeds the audio straight back into Deepgram, and compares the
transcript to what was said — with and without the `numerals` + `keyterm` tuning in
`stt.py`. The column that matters is **whether the order number survived**: "4471" heard
as "four four seven one" is a tool call the agent has to guess at, and a guessed digit is
a refund against the wrong order. It also prints the latency budget (STT finalise / LLM
first token / TTS first byte). Target: end-of-speech → first audio in 700–1200 ms.

Turn-taking is the other big latency lever: set `TURN_DETECTION=semantic` to end turns on
*meaning* instead of silence (it also stops the agent interrupting people who pause to
think). Falls back to VAD if unavailable.

## 1. Compare the two TTS engines (latency)

```bash
voice/.venv/bin/python voice/bench_tts.py
```

Prints time-to-first-byte (TTFB) and real-time factor for Deepgram Aura and
Sarvam over the same support sentences. Lower TTFB = snappier first word. Flip
`TTS_PROVIDER` in `.env` to whichever wins for your audience (remember Sarvam's
English is Indian English).

## 2. Talk to the agent

First start the backend in another terminal — the tools call it:

```bash
make run          # FastAPI on :8000 (BACKEND_URL in voice/.env)
```

Zero-infra terminal test (uses your mic/speakers, no LiveKit Cloud room needed —
only the provider keys):

```bash
voice/.venv/bin/python voice/agent.py console
```

Or run it as a real LiveKit worker and join from the browser:

```bash
voice/.venv/bin/python voice/agent.py dev
```

Then open the **LiveKit Agents Playground** (<https://agents-playground.livekit.io>),
connect it to your LiveKit Cloud project, and start talking. Per-turn latency
(end-of-utterance → first audio) is logged to the worker console.

## 3. The approval call — the agent phones a human

When policy gates an action, a human can decide it **out loud**. Run the approver
worker alongside the support agent (separate process — it has an explicit
`agent_name`, so it is dispatched on demand rather than joining every room):

```bash
voice/.venv/bin/python voice/approver_agent.py dev
```

Then hit **“Call a human”** on any pending approval in the console. The agent joins
the call, reads out the action and why it needs a human, takes a spoken decision, and
submits it — which resumes the paused graph.

* With `LIVEKIT_SIP_TRUNK_ID` + `APPROVER_PHONE` set, **it rings a real phone**.
* Without a trunk it still works: the console joins the same room in the browser. So
  you can demo the whole thing for free; adding a phone number later is config, not code.
* **Set `APPROVER_PIN`.** Whoever answers the call could otherwise approve a refund —
  `submit_decision` refuses until the spoken PIN checks out.

## Files

| File | What |
|---|---|
| `config.py` | Env-driven settings (keys + latency knobs). |
| `tts.py` | `build_tts()` — the Deepgram/Sarvam A/B factory. |
| `agent.py` | The support worker (STT → LLM → TTS loop + the HITL tools). |
| `support_agent.py` | The caller-facing agent: identity gate, reads, gated actions. |
| `approver_agent.py` | The **approval call** — briefs a human, takes a spoken decision. |
| `backend.py` | Thin RPC client for the HITL backend. |
| `bench_tts.py` | The TTS latency benchmark. |
