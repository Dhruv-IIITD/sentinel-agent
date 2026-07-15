# Voice HITL — Voice Customer-Support Ops Agent (Build Plan)

> Evolves the existing HITL engine into a **real-time voice customer-support
> agent**: a caller talks to it, it takes **real** account actions (refund,
> cancel, address change), auto-executes low-risk ones, and routes high-stakes
> ones through a **human approver** — pausing mid-call and resuming after the
> decision. The LangGraph pause/persist/resume engine we already built becomes
> the **brain**; the voice layer is the new surface.
>
> **Focus:** best achievable **latency**, **accuracy**, and a build that reads as
> a real product, not a demo. Read `docs/BUILD_PLAN.md` for the engine this sits
> on top of.

## North star (the demo)

1. Caller: *"Refund my order 4471, it arrived damaged."*
2. Agent verifies the caller's identity, looks up the order (instant read), and
   confirms the details aloud.
3. Agent calls `issue_refund($180)` → backend policy-gate → **approval required**.
4. Agent: *"That refund needs a quick supervisor approval — I can hold about a
   minute, or call you back. Which do you prefer?"*
5. A supervisor approves in the dashboard (or by voice) → the graph **resumes** →
   executes **exactly once**.
6. Agent: *"Approved — your $180 refund is on its way, 3–5 business days."*

The human-in-the-loop step becomes **audible**. That's the signature.

## Stack (decided)

| Layer | Choice | Why |
|---|---|---|
| Media / orchestration | **LiveKit Agents** (Python) | Best-in-class WebRTC + STT/LLM/TTS pipeline, turn-taking, barge-in, SIP telephony. |
| STT | **Deepgram Nova-3** (streaming) | Top latency+accuracy for English; streaming partials. |
| LLM | **Groq** (`llama-3.3-70b-versatile`) | Fastest inference for open models — latency is everything in voice. Already integrated. |
| TTS | **Pluggable — A/B `Deepgram Aura-2` vs `Sarvam`** (Cartesia Sonic as a 3rd option) | Decide on *measured* latency/quality, not spec sheets. See Phase 1. |
| Turn detection | **LiveKit semantic turn detector** | Ends turns on meaning, not silence timeout → cuts perceived latency. |
| Brain | **existing FastAPI + LangGraph** | Risk gate, policy-RAG, idempotency, audit, approvals, HITL interrupt/resume. |

**TTS is pluggable** (same pattern as our pluggable LLM provider) so we can flip
`Deepgram Aura` ↔ `Sarvam` via env and benchmark both. Default after A/B TBD.

**LiveKit SIP cost:** the SIP bridge is **free/open-source** (included in LiveKit
Cloud) and **browser calls are 100% free**. Only a real **phone number + PSTN
minutes** cost money (Twilio/Telnyx, a few $/mo + per-minute). Build & demo free
over the browser; add a number only for the "call a real number" wow (Phase 4).

## Architecture — fast loop + HITL brain (Pattern A)

```
┌─────────────┐   audio    ┌──────────────────────┐  tool RPC  ┌────────────────────────┐
│  Frontend   │◀──WebRTC──▶│   Voice Worker        │◀─────────▶│  Backend (the engine)  │
│ (Next.js +  │            │  (LiveKit Agents)     │           │  FastAPI + LangGraph   │
│ LiveKit JS) │            │  Deepgram→Groq→TTS    │           │  risk gate · policy-RAG│
└─────────────┘            └──────────────────────┘           │  idempotency · audit   │
      ▲  approval inbox / timeline / audit (REST + SSE)  ─────▶│  approvals · HITL      │
      └──────────────────────────────────────────────────────┘└────────────────────────┘
```

**The decision that determines latency: keep the conversational loop and the HITL
graph separate.**

- The **voice worker** runs the tight STT→LLM→TTS loop. Its LLM tools are thin
  **RPC calls** to the backend.
- **Read tools** (order status, tracking, policy) return instantly and are spoken
  back — *the LangGraph graph is NOT in this hot path.*
- **Side-effecting tools** (refund, cancel, address change) route into the
  existing **risk gate**: auto-tier executes and returns; high-stakes returns
  `approval_required` + an id, and the voice agent verbalizes the wait, then
  resumes when the backend signals approval.

One shared `session_id` ties the voice session's chat memory to the graph's
`thread_id`. The graph earns its keep on **actions** (gating, idempotency,
resume, audit), not on chit-chat.

## What the agent can do (tools by risk tier)

| Tier | Tools | Behavior |
|---|---|---|
| **Read (auto)** | `get_order_status`, `track_shipment`, `check_refund_eligibility`, `get_policy` (RAG), `lookup_customer` | Instant, spoken back. No gate. |
| **Reversible (auto, logged)** | `update_shipping_address` (pre-dispatch), `add_order_note`, `resend_confirmation`, small goodwill credit < $X | Execute + audit. |
| **Dynamic (policy decides)** | `issue_refund`, `issue_store_credit` | Policy-RAG decides gate vs auto by amount/window at runtime. |
| **High-stakes (always approval)** | `cancel_order`, `change_account_email`, `price_override`, `expedite_at_cost` | Always pause for a human. |

Two **voice-specific** tools:
- **`verify_identity`** — before *any* account action over the phone, verify the
  caller (order # + email/zip, or an OTP). Table-stakes security for voice.
- **`escalate_to_human`** — warm-transfer (or ticket) with an auto-summary, for
  angry callers or out-of-scope asks.

## Latency strategy (the #1 goal)

**Target:** end-of-user-speech → first agent audio in **~700ms–1.2s**.

| Stage | Budget | Lever |
|---|---|---|
| STT finalize | 100–300ms | streaming partials + semantic turn detection (don't wait on silence) |
| LLM first token (Groq) | 100–300ms | Groq + lean system prompt + tight tool schemas |
| LLM → first sentence | overlap | **stream tokens into TTS sentence-by-sentence** |
| TTS first audio | 90–400ms | streaming TTS; measure Aura vs Sarvam |
| Buffers/network | 50–150ms | colocate worker + providers in one region; prewarm |

**Three tricks that matter most:** (1) semantic turn detection, (2) sentence-level
streaming from LLM straight into TTS, (3) keep the graph out of the hot path.
Ship a **latency HUD** in the frontend early so every change is measured.

## Phases (each ends in a demo)

**Phase 0 — Foundations.** ✅ **Done.** Keys (LiveKit, Deepgram, Sarvam, Groq).
Domain + tool catalog + tiers locked. Latency budget. Pattern-A architecture.
Repo layout: voice worker in `voice/` with its own venv. Language: English (US).

**Phase 1 — Bare voice loop + TTS A/B (the latency gate).** ✅ **Built.** LiveKit
worker (`voice/agent.py`): Deepgram Nova-3 → Groq llama-3.3-70b → pluggable TTS
(`voice/tts.py`), latency-tuned. `voice/bench_tts.py` measures TTFB/RTF for
**Deepgram Aura vs Sarvam** over support-style sentences.
*Remaining:* run the benchmark + `agent.py console` with real keys, pick the TTS default.

**Phase 2 — Read-only tools (grounded voice).** ✅ **Done & verified end-to-end.**
Backend RPC surface (`src/app/api/voice.py`) + voice tools (`voice/support_agent.py`):
`verify_identity`, `get_order_status`, `track_shipment`, `check_refund_eligibility`,
`get_refund_policy`. The **identity gate is enforced in the tool layer, per-order** —
a read tool refuses until verification succeeds, so a jailbroken prompt can't talk
past it. `check_refund_eligibility` runs the *same* policy engine that gates the real
action, so what the caller is told matches what would actually happen.

**Phase 3 — Actions + the HITL gate (the core).** ✅ **Done & verified end-to-end.**
`POST /voice/action` seeds the voice model's chosen tool call at the `agent` node
(`aupdate_state(as_node="agent")`) and lets the **real graph** gate it — so a refund
started by voice is checkpointed, lands in the **same dashboard queue**, resumes via
the same `Command(resume=...)`, and is protected by the same idempotency ledger as a
chat one. There is no second, weaker path for voice.
The **"please hold" UX**: the tool speaks *before* it blocks (`session.say`), polls
for the decision, reassures every 25s, and times out after 120s. The agent may never
claim success on its own — tools return an explicit DONE / APPROVED / DECLINED /
PENDING verdict.
*Verified:* unverified refund refused → $20 refund auto-executes (policy) → $180
refund pauses, agent holds, supervisor approves in the dashboard, graph resumes,
executed **exactly once** → cancel_order rejected, no side effect.

> **Landmine found here (worth remembering):** resume is delivered as
> `Command(resume={tool_call_id: decision})`, and LangGraph reads a resume dict whose
> keys parse as UUIDs as a `{task_id: value}` map. A bare `uuid4().hex` *is*
> UUID-parseable, so it matched no task, the interrupt silently re-raised, and the
> refund never executed. Voice tool-call ids are therefore prefixed (`call_…`), like a
> real model's. Pinned by `test_voice_tool_call_ids_are_never_uuid_shaped`.

**Phase 4 — Voice/phone approval (the wow).** ✅ **Done & verified end-to-end.**
`POST /voice/approval-call/{id}` dispatches a second agent (`voice/approver_agent.py`,
registered with an explicit `agent_name` so it is dispatched on demand, never into
every room). It reads the approval id from the job metadata, briefs whoever picks up,
takes a **spoken** decision, and submits it through the *same* decision endpoint the
dashboard uses — resuming the paused graph. The human in the loop, out loud.

**It demos for free.** With a SIP trunk it rings a real phone; without one the same
call happens in a browser room — the console's **"Call a human"** button joins it. Adding
a trunk later is config, not code. (The LiveKit SIP bridge is free; only the phone
number + PSTN minutes cost money.)

Two deliberate choices:

* **The briefing is spoken verbatim, not generated.** `session.say()` reads a scripted
  line built from the approval row, so the amount, the order, and the reason a human is
  asked to approve are exactly what is in the queue — an LLM cannot paraphrase a refund
  into the wrong number. Only the conversation *after* the briefing is modelled.
* **A spoken PIN gates the decision.** Whoever answers the phone could otherwise approve
  a refund. `submit_decision` refuses until `verify_approver` succeeds — enforced in the
  tool layer, not the prompt, exactly like the caller identity gate. Spoken digits are
  normalised ("2-4 6 8" → `2468`).

*Verified:* approve-without-PIN refused → wrong PIN refused → correct PIN accepted →
spoken approval recorded → **paused graph resumed and the refund executed exactly
once** → double-submit refused → the caller's held agent saw `settled=true`.
The dispatch/SIP call itself needs real LiveKit credentials, so only its guard paths
(503 / 404 / 409) are unit-tested.

**Phase 5 — The product frontend.** ✅ **Built.** A **Vite + React + TypeScript**
console in `web/`, served by FastAPI at `/ui` (single deploy, no CORS, no separate
host). `POST /voice/token` mints the LiveKit join token so you can talk to the agent
from the browser.

* **Live call** — LiveKit room with a bar visualizer, agent state (listening /
  thinking / speaking), a live transcript, and — the good bit — an **"agent paused
  this call, waiting on your approval"** banner, because the token response hands back
  the same `thread_id` the voice worker uses.
* **Approval queue** — auto-refreshing cards showing the **retrieved policy clause**
  that forced the gate, editable args for *Modify*, plus **Preview** and **What if?**
  (counterfactual replay).
* **Activity** — every action logged, with **Reverse** on compensable ones.
* **Text tab** — the console still works with no LiveKit keys at all.

Design follows the validated palette: the four **status colors are reserved and
identical in both themes**, and never carry meaning alone — every badge pairs the
color with an **icon and a text label** (on the light surface `warning`/`serious` are
sub-3:1 by design, so the label *is* the accessible channel). Light + dark both ship.
LiveKit is **code-split** (initial bundle 759kB → **158kB**; the 601kB call chunk
loads only when someone actually starts a call).

*Not verified visually here* — this sandbox has no browser, so run `make web && make
run` and look at <http://localhost:8000/ui>.

**Phase 6 — Latency & accuracy hardening.** ✅ **Done.**

**The security hole we closed first.** The caller identity gate lived only in the voice
worker's tool layer — so the *backend* would hand over order details, or run a refund,
to anyone who asked with a `thread_id`. A jailbroken prompt, a buggy worker, or a plain
`curl` bypassed it entirely. It is now enforced **server-side**
(`api/voice.py::_require_verified`): no read and no action on an order the caller never
proved they own, checked *before* the graph is even touched. The agent-side check stays
as a fast, friendly refusal. **The prompt is not a security boundary.**

**STT tuning that is really a correctness fix** (`voice/stt.py`):

* `numerals=True` — Deepgram writes spoken numbers as digits, so "order four four seven
  one" arrives as `4471`. Without it the model must reconstruct the order number from
  words, and **one wrong digit is a refund against someone else's order**. (Measured:
  the untuned transcript of that phrase scores 100% WER *and loses the order number
  entirely*.)
* `keyterm` boosting — the domain's vocabulary ("store credit", "damaged", the product
  names), which is exactly what a general model drops.

**Turn taking** — `TURN_DETECTION=semantic` ends a turn on *meaning* rather than on
silence: lower perceived latency, and it stops the agent cutting people off when they
pause to think. Runs on LiveKit's inference service; falls back to VAD. Default is `vad`,
because that is the one we can guarantee works out of the box.

**The eval** (`make eval-voice`, in CI) drives the **real** voice surface end to end, so
it asserts what the router-level evals cannot: not merely that the gate *said* "stop",
but that **no money moved** — every gated case is re-checked against the store.

| | |
|---|---|
| Identity gate | **6/6 unauthorised attempts refused** (reads, refund, cancel, cross-call) |
| Gate integrity | **100% recall · 0% false-escalation · 0 unapproved executions** (18 voice-reachable gold cases) |
| Injection, spoken | **0% attack-success** (9 attacks, assuming the model is fully manipulated) |

`voice/bench_pipeline.py` measures the rest with real keys: word error rate boosted vs
control, whether the order number survived, and the latency budget (STT finalise / LLM
first token / TTS first byte). *Its live-API path is unverified here — no keys in this
sandbox.*

**Phase 7 — Observe, deploy, polish.** ✅ **Done.**

**`GET /metrics`** — the numbers that decide whether a human-in-the-loop system is
actually working, all derived from the audit log + approval queue so they *cannot drift
from what happened*:

* **Autonomy rate** — the share of actions handled without a human. The whole economic
  argument. Too low and you built an expensive form; too high and the gate probably isn't
  catching anything.
* **Time to decision (p50/p95)** — on a voice call this is not a dashboard statistic, it
  is **how long the caller was on hold**.
* **Override rate** — how often a human declined or edited the agent's proposal. The
  earliest signal that its judgement (or the policy) has drifted.
* **Reversals + tool latency** — `latency_ms` was a column nothing ever wrote; it is now
  measured at execution.

Rendered in the console's **Operations** panel (nulls show as `—`, never a fake `0`).

**Deploy** — `docker compose up` runs db + api + console; `--profile voice` adds both
LiveKit workers (`voice/Dockerfile`, one image, two commands). Fixed on the way: the API
image never copied `data/`, so **the policy RAG would have found zero documents in a
built image** and silently fallen back to hardcoded thresholds. [`docs/DEPLOY.md`](DEPLOY.md)
covers the four processes, which key unlocks what, and the restart proof to run against
the real deployment.

*Docker itself is unavailable in this sandbox — the compose file and Dockerfiles are
structurally validated but the images were never built here.*

---

**Original Phase 7 plan.** LangSmith traces + LiveKit analytics; cost/
latency/token dashboard. Deploy backend + worker + frontend to a live URL (+
optional number). Demo script, 60-sec video, README, architecture diagram.

## Backlog (add later)

Multilingual mid-call switching (Sarvam shines) · sentiment-based escalation ·
warm transfer with summary · call-back when approver unavailable · CSAT after
call · fraud/risk signals feeding confidence-escalation · FAQ knowledge-base RAG ·
analytics (containment rate, AHT, approval rate) · barge-in polish.

## Frontend & backend, concretely

- **Backend (reuse + extend):** FastAPI + LangGraph engine stays the brain — add a
  thin voice-tools RPC surface, a `call/session` model, and `verify_identity`.
  Postgres for durable approvals/audit/checkpoints.
- **Voice worker (new):** LiveKit Agents Python worker — the STT/LLM/TTS pipeline +
  the "waiting for approval" state machine. Lives in `voice/` (monorepo).
- **Frontend (new):** Next.js + React + LiveKit JS/React SDK — call UI, approval
  inbox, timeline, history/postmortem, latency HUD. Deploy on Vercel.

## Open decisions (settle in Phase 0)

- **Language/accent for v1:** English-first vs Indian English vs multilingual
  (English + Hindi/Indic). Swings STT model + TTS voice choice.
- **Default TTS:** decided by the Phase-1 A/B (Deepgram Aura vs Sarvam).
- **Telephony:** browser-only for v1; SIP + real number later.
- **Repo layout:** monorepo — voice worker in `voice/`, frontend in `ui/` (or
  `web/`).
