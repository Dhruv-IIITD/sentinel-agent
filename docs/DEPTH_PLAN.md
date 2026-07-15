# Depth & Scale — making it production-grade

> The [master plan](MASTER_PLAN.md) covers *what the product does*. This one covers *what
> makes it look like a team built it over months* rather than a weekend: real-time
> infrastructure, async reliability, auth & multi-tenancy, observability, and rigorous
> evaluation.
>
> **The governing principle:** every addition here fixes a *real problem the system has*.
> Cargo-culted infrastructure ("I added Kafka") reads as junior in an interview; "I added
> Redis because per-process state broke across workers" reads as senior. Each item states
> the problem first.

---

## The tracks

### Track 1 — Real-time & shared state  *(Redis + WebSockets)*

**The real gap it fixes.** Today, `app.state.verified` (which callers are verified) and
the in-memory idempotency ledger live **inside a single process**. Run two API workers, or
restart without Postgres, and a caller verified on worker A is a stranger to worker B, and
the exactly-once guarantee is only exactly-once *per process*. That is a genuine
distributed-systems bug. And the console **polls every 2 seconds** for new approvals — a
caller on hold feels every bit of that lag.

**What we build**
- **Redis as the shared store** for verification sessions, the idempotency ledger, and
  rate-limit counters — so identity and exactly-once are correct across N workers.
- **Redis Pub/Sub → WebSockets**: when an approval is created or resolved, push it to every
  connected console instantly. Polling disappears; the queue updates in real time.
- **Rate limiting** (token bucket in Redis) per caller / per tenant — real abuse protection.
- **Caching**: policy-retrieval results and hot order lookups, with TTLs.

**Why it's impressive:** it turns a single-process demo into a horizontally-scalable
service, and the reasoning ("state was per-process, so I moved it to Redis") is exactly
what a staff engineer asks about.

---

### Track 2 — Async work & scheduling  *(background workers)*

**The gap.** Sending an email, calling Stripe, placing an outbound approval call, and
retrying a failed provider all block the request that triggered them — and there is no way
to make something happen *later*.

**What we build**
- A **background worker** (`arq` on Redis, or Celery) for out-of-band work: emails,
  Stripe refunds, webhooks, retries with exponential backoff and a dead-letter queue.
- **SLA escalation timers** — the standout feature: if an approval isn't decided within N
  minutes, escalate to a manager, re-notify, or auto-reject per policy. Needs a scheduler;
  reads as "someone who has run real support ops built this."
- **Scheduled jobs**: nightly reconciliation, stale-session cleanup, metric rollups.

**Why it's impressive:** async + scheduling + retries + DLQ is the backbone of every real
backend, and SLA timers are a feature reviewers remember.

---

### Track 3 — Auth, RBAC & multi-tenancy

**The gap.** Anyone can approve anything; there are no users, roles, or tenants. That's the
biggest "it's a demo" tell.

**What we build**
- **Authentication** — JWT/OAuth login for operators.
- **RBAC** — operator / supervisor / admin, with **per-role approval limits** (a $5k refund
  needs a manager; an admin can change policy).
- **Multi-approver quorum** — high-value actions require two independent sign-offs.
- **Multi-tenancy** — multiple stores, each with isolated data *and its own policy
  document*, selected by tenant. One deployment, many "customers."

**Why it's impressive:** RBAC + quorum + multi-tenant is the shape of a real SaaS, and it
deepens the project's actual theme (human oversight) rather than bolting on unrelated
features.

---

### Track 4 — Reliability & correctness

**The gap.** A provider outage kills a call; the audit log is trusted but not
tamper-evident; we have no numbers under load.

**What we build**
- **Provider failover** — LiveKit `FallbackAdapter` for TTS/STT/LLM (Deepgram → Sarvam,
  Groq → Anthropic) so one provider's outage degrades instead of dropping the call.
- **Circuit breakers** on external calls (Stripe, providers).
- **Tamper-evident audit log** — each entry stores a hash of `(previous_hash + this_row)`,
  forming a chain; any edit to history breaks the chain and is detectable. Cheap to build,
  and it signals you think about auditability and compliance.
- **Load tests** (`k6` / Locust) with **published p50/p95** under concurrent calls, plus a
  **chaos test** that kills a worker mid-approval and proves recovery + exactly-once.

**Why it's impressive:** failover, a hash-chained audit trail, and real load numbers are
the difference between "it works" and "it holds up."

---

### Track 5 — Observability & SRE

**The gap.** When a call misbehaves, we grep logs across two services by hand; `/metrics`
is JSON, not a dashboard; there's no distributed trace.

**What we build**
- **Structured JSON logging** with a **correlation ID** threaded across voice worker → API
  → graph → tools, so one call is one searchable trace.
- **OpenTelemetry** (LiveKit already emits it) → **Jaeger/Tempo** for distributed traces.
- **Prometheus + Grafana** dashboards: autonomy rate, time-to-decision, turn latency
  percentiles, provider error rates, cost per conversation.
- **Alerting** on SLA breaches and error-rate spikes.

**Why it's impressive:** an actual Grafana screenshot in the README is worth a thousand
words, and correlation-ID tracing across services is a senior habit.

---

### Track 6 — Agent & ML sophistication

**The gap.** The evals are good but narrow; retrieval is keyword-first; every turn pays for
the big model.

**What we build**
- **Expanded eval suite** — LLM-as-judge for answer quality, a red-team corpus for
  jailbreaks, retrieval-quality (precision@k), latency SLOs — trend-tracked in CI so
  regressions are caught.
- **Hybrid retrieval** — BM25 + vector with a **reranker**, evaluated against the keyword
  baseline.
- **Multi-model routing** — a cheap/fast model for chit-chat, the big model for reasoning
  and tool calls, with the **measured cost/latency tradeoff** published.
- **Semantic LLM caching** (Redis) for repeated questions.
- **Confidence calibration** — tie the confidence-escalation threshold to measured
  reliability rather than a guess.

**Why it's impressive:** it shows the AI half is engineered and measured, not vibes.

---

### Track 7 — Product surface

The features that make the actions matter (detailed in [MASTER_PLAN](MASTER_PLAN.md)):
**Stripe test-mode refunds** (real dashboard), **real confirmation emails**, **Customer
360 cockpit**, more tools (partial refund, reship, returns, discounts, escalate),
**cross-call memory**, **proactive outbound calls**, **multilingual** (Sarvam Indic —
switch language mid-call), **sentiment-based escalation**, and **auto call-summaries /
postmortems**.

---

### Track 8 — Deploy & craft

**What we build**
- A **live URL** + optional **phone number** (LiveKit SIP + a trunk).
- **Kubernetes/Helm** manifests (or Fly.io) — signals you can ship at scale.
- **ADRs** (architecture decision records) documenting the key calls (why Pattern A, why
  seed state at the agent node, why hash-chained audit).
- **OpenAPI** docs (FastAPI gives it for free — surface it), architecture diagrams.
- A **2-minute demo video** — the single highest-leverage artifact for a recruiter.

---

## Ranked by signal-per-effort

1. **Real-time + multi-worker-correct state** (Redis + WebSockets) — fixes a real gap, instantly visible.
2. **SLA escalation timers + background queue** — memorable "real ops."
3. **Auth + RBAC + multi-approver quorum + multi-tenancy** — reads as enterprise SaaS.
4. **Stripe test refunds + real email** — the biggest "not a toy" moment.
5. **Tamper-evident audit log** — cheap, high compliance signal.
6. **Observability stack** (OTel + Prometheus + Grafana) — an SRE habit, great screenshots.
7. **Expanded evals + load testing** — rigor, quotable numbers.
8. **Deploy live + demo video** — what a recruiter actually clicks.

---

## A realistic 4-week build order

| Week | Theme | Ships |
|---|---|---|
| **1** | Real-time & correctness | Redis (shared verification + idempotency), Pub/Sub → WebSockets console, rate limiting, caching. *The app becomes multi-worker-correct and live.* |
| **2** | Async & real actions | Background queue, **SLA escalation timers**, retries + provider failover, tamper-evident audit, **Stripe test refunds + email**. |
| **3** | Enterprise | Auth, RBAC, per-role limits, **multi-approver quorum**, multi-tenancy, **Customer 360 cockpit**. |
| **4** | Prove & ship | OpenTelemetry + Prometheus + Grafana, expanded eval suite + load tests, **deploy live + phone number**, ADRs + **demo video**. |

Each week ends in something demoable and a new line on the résumé.

---

## What we deliberately will NOT add

Restraint is a senior signal too. These would be cargo cult here:

- **Kafka / event sourcing everywhere** — Redis Streams + Postgres cover our throughput;
  Kafka would be infrastructure with no load to justify it.
- **A microservice per noun** — the voice worker / API / worker split is already the right
  seam. More services would be complexity for its own sake.
- **A second database** (Mongo, etc.) — Postgres + pgvector + Redis is the complete, and
  correct, storage story.
- **A custom model / fine-tune** — the value here is the *system* (oversight, safety,
  durability), not a model. Prompt + eval + routing beats a fine-tune for this problem.

Naming each of these — and why we skipped it — is worth a sentence in the README. Knowing
what *not* to build is the hardest thing to demonstrate.
