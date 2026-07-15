# CLAUDE.md — HITL Agent

> This file orients any Claude Code session started in this repo. Read
> `docs/DESIGN.md` for the full design brief before doing substantial work.

## What this project is

A **Human-in-the-Loop (HITL) tool-using agent**: an agentic AI system that
answers questions, looks things up, and **takes real, side-effecting actions**,
but routes high-stakes actions through a human for approval — pausing
mid-execution and resuming after the decision, even across process restarts.

The signature mechanic is **pause → persist → resume**: the LangGraph graph
suspends at an approval node, saves its entire state to a database, and resumes
from that exact state once a human approves / rejects / modifies the action.

## Why this project (context)

Chosen over other portfolio ideas (agentic RAG, text-to-SQL, multi-agent
research, code-review agent) because it is the **rarest and most impactful**:
almost all portfolio GenAI projects are read-only chatbots, whereas this one
takes *real actions* with human oversight — the frontier enterprises actually
deploy. It also exercises the most transferable agentic skills (tools, state,
safety, human oversight) while staying achievable for one person.

## Status

🟢 **Phase 2 complete.** On top of Phases 0–1 (scaffold + the interrupt/resume
graph), the "impressive" tier is in and verified (**40 tests pass**):
**policy-RAG drives routing** — retrieved policy decides at runtime whether a
refund needs approval, and editing the policy doc changes routing with no code
change; **guardrails** (PII redaction at the audit boundary, a hard refund cap
that always gates); **compensation/rollback** (reverse a refund via the same
idempotency ledger, with a dashboard "Reverse" button); **confidence-based
escalation** (gate even auto actions when the agent is unsure); and **SSE
streaming** (`/chat/stream` live step trace).

🟢 **Phase 3 complete + prod-hardening done** — **54 tests pass**. The **eval
harness** gives two quotable numbers (`make eval`, `make eval-injection`):
routing **flags 100% of actions needing approval with 0% false-escalation** on a
24-case gold set; and **0% prompt-injection attack-success** across 10 attempts.
Checkpointer-facing extras: **counterfactual replay** (`POST /threads/{id}/
counterfactual` forks a paused approval and plays out approve *and* reject on
sandbox stores via `aupdate_state`, mutating nothing real), **outcome preview**
(`/approvals/{id}/preview` dry-runs a decision), and the **time-travel
inspector** (`/threads/{id}/history`).

Three prod items are now also done: (1) a **vector/pgvector retriever** with a
pluggable `Embedder` (`RETRIEVER=vector`; in-memory index in dev, pgvector +
`scripts/ingest_policies.py` in prod); (2) a **SQLite checkpointer backend** and
`scripts/prove_restart.py` that **proves pause→resume across a real process
restart with no Docker** (verified: process 1 pauses & exits, a fresh process 2
resumes and executes exactly once); (3) **GitHub Actions CI** + **LangSmith**
tracing docs (`docs/OBSERVABILITY.md`). See `docs/BUILD_PLAN.md`.

## Stack (decided)

- **LangGraph** — graph orchestration, `interrupt()`, persistent checkpointer
- **LangChain** — tool definitions + retrieval
- **Claude (Opus/Sonnet)** — reasoning model (via `langchain-anthropic`)
- **FastAPI** — streaming chat endpoint + approval endpoints
- **Postgres** — checkpointer state + audit log + app data (one DB)
- **pgvector** + reranker — policy/knowledge-base RAG
- **LangSmith** — tracing/observability
- **Docker** — packaging

## Core design pillars

1. **Risk-tiered tools** — read/reversible actions auto-execute; high-stakes
   actions require approval; a *dynamic* tier is decided at runtime by policy.
2. **Policy RAG drives HITL routing** — retrieved policy decides, at runtime,
   whether an action needs a human, and justifies the decision. (This is how
   RAG is fused into the agent rather than bolted on.)
3. **Pause / persist / resume** — LangGraph `interrupt()` + Postgres
   checkpointer; conversations are tracked by `thread_id`.
4. **Auditable & safe** — every action + decision logged; idempotency keys and
   compensating actions prevent double-execution.

## Open decisions (settle these in the plan)

- **Domain**: e-commerce customer-support ops (default, relatable, natural risk
  gradient) vs. IT/DevOps ops vs. finance approvals.
- **Approval surface**: minimal web dashboard first vs. straight to Slack
  approvals.

## Next step

The build plan is complete — see `docs/BUILD_PLAN.md` (architecture, data model,
the LangGraph node graph, interrupt/resume loop, tool tiers, RAG layer, phased
sequence with per-phase Opus 4.8 effort levels, and extra features). Open
decisions are settled there: **domain = e-commerce support**, **approval surface
= web dashboard first**. Phase 0 is done; **Phase 1 (the agent graph) is next.**

## Conventions

- Python 3.12. Keep secrets in `.env` (see `.env.example`), never commit them.
- Nothing is committed to git yet, so the plan can freely reshape structure.
