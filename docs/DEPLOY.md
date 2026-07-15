# Deploying

Four processes, and only the first two are required:

| Process | What it is | Needed for |
|---|---|---|
| **API + console** | FastAPI; serves the React console at `/ui` | everything |
| **Postgres** | checkpointer + audit + approvals + pgvector | durability (pause→resume across restarts) |
| **voice-agent** | LiveKit worker — takes the calls | talking to it |
| **approval-agent** | LiveKit worker — phones a human for sign-off | approval calls |

The console, the approval queue, the audit log, counterfactual replay and every eval
work with **no voice keys at all**. Voice is additive.

## Locally

```bash
docker compose up                    # db + api + console -> http://localhost:8000/ui
docker compose --profile voice up    # ...plus both LiveKit workers
```

The API image builds the console in a Node stage and copies `web/dist` in, so there is
no separate frontend deploy and no CORS.

## To a real URL

The cheapest setup that is genuinely production-shaped:

| Piece | Where | Notes |
|---|---|---|
| API + console | Fly.io / Render / Railway | one container, the `Dockerfile` at the repo root |
| Postgres | Neon / Supabase / Fly Postgres | free tiers; **must have `pgvector`** if `RETRIEVER=vector` |
| Voice workers | Fly.io / Render / **LiveKit Cloud agents** | `voice/Dockerfile`, one per command |
| LiveKit | LiveKit Cloud | free tier; browser calls cost nothing |
| Phone number | Twilio / Telnyx → LiveKit SIP | the only part that costs money |

Sketch, using Fly:

```bash
fly launch --dockerfile Dockerfile --no-deploy       # the API + console
fly postgres create && fly postgres attach <db>      # sets DATABASE_URL
fly secrets set GROQ_API_KEY=... LIVEKIT_URL=... LIVEKIT_API_KEY=... LIVEKIT_API_SECRET=...
fly deploy

# each voice worker is its own app, same image, different command
fly launch --dockerfile voice/Dockerfile --name hitl-voice --no-deploy
fly secrets set BACKEND_URL=https://<your-api>.fly.dev DEEPGRAM_API_KEY=... GROQ_API_KEY=... \
                LIVEKIT_URL=... LIVEKIT_API_KEY=... LIVEKIT_API_SECRET=... APPROVER_PIN=...
fly deploy
```

Workers hold a persistent WebSocket to LiveKit and take real-time audio, so **do not put
them on a platform that scales to zero** — a cold start mid-call is a dropped call.

## Which key unlocks what

| Key | Required? | Without it |
|---|---|---|
| `GROQ_API_KEY` | **yes** | the agent cannot reason |
| `DATABASE_URL` | no | in-memory: the queue and audit reset on restart |
| `LIVEKIT_*` | for voice | the console's call buttons return 503; text chat still works |
| `DEEPGRAM_API_KEY` | for voice | no speech in or out |
| `SARVAM_API_KEY` | no | only for the Sarvam side of the TTS A/B |
| `LIVEKIT_SIP_TRUNK_ID` + `APPROVER_PHONE` | no | approval calls happen in a browser room instead of ringing a phone |
| `APPROVER_PIN` | **set it** | anyone who answers the approval call can approve a refund |
| `LANGSMITH_API_KEY` | no | no tracing (zero overhead when off) |

## Before you call it deployed

```bash
curl https://<your-api>/healthz
curl https://<your-api>/metrics     # autonomy rate, time-to-decision, override rate
```

Then open `/ui`, send *"refund order 4471"*, and watch it pause. If the approval lands in
the queue and the graph resumes when you decide, the whole mechanism is live.

**Restart proof.** The claim worth testing on the real deployment: gate a refund, restart
the API container *while the approval is pending*, then approve it. It should still
execute — exactly once. That is the entire point of the checkpointer, and it is the one
thing an in-memory deploy silently cannot do.

## Observability

- **LangSmith** — set `LANGSMITH_TRACING=true`; see [OBSERVABILITY.md](OBSERVABILITY.md).
  Answers *what did the agent think*.
- **`GET /metrics`** — autonomy rate, time-to-decision (p50/p95), override rate, tool
  latency, reversals. Derived from the audit log, so it cannot drift from what happened.
  Answers *how is the loop doing*. Rendered in the console's **Operations** panel.
- **Worker logs** — the LiveKit workers log per-turn latency (end-of-utterance → first
  audio) via `metrics.log_metrics`.
