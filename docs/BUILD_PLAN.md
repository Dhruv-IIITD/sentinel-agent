# HITL Agent — Build Plan

The execution plan for the Human-in-the-Loop tool-using agent. Reads on top of
[`DESIGN.md`](DESIGN.md) (the *why*) — this doc is the *how*: settled decisions,
architecture, data model, the LangGraph interrupt/resume loop, the phased build
sequence with a recommended Claude Opus 4.8 **effort** level per phase, and the
extra features that make it resume-grade.

---

## 0. Settled decisions

- **Domain → e-commerce customer-support ops.** Cleanest natural risk gradient
  (look up order → change address → refund/cancel/credit); instantly legible in
  a demo. All business logic sits behind a thin `domain/` layer so an IT/DevOps
  variant is a later swap, not a rewrite.
- **Approval surface → minimal web dashboard first; Slack is a later add.**
  Ships in-repo with no external OAuth or public tunnel, so the core
  pause/resume mechanic is provable on day one. Decision delivery is modelled as
  an `ApprovalChannel` interface so Slack drops in behind the same contract.

## 1. Architecture

```
   HTTP / SSE   ┌──────────── FastAPI ────────────┐
  ───────────►  │ /chat (stream)  /approvals  /audit │
                └───┬──────────────────────▲─────────┘
             invoke │        Command(resume=decision)
                    ▼                       │
        ┌──────── LangGraph app ────────────┴──┐
        │ agent ⇄ classify_risk ⇄ approval ⇄ exec│
        │        interrupt() suspends here       │
        └──┬───────────────┬──────────────┬──────┘
   Postgres│         pgvector│         Claude│
  checkpointer      policy RAG      (Anthropic)
   + audit + app     + reranker
```

One Postgres instance, three concerns: **LangGraph checkpoints** (pause/resume
state), **app tables** (audit + approvals + business data), and **pgvector**
(policy/KB embeddings).

## 2. Folder structure

```
src/app/
  main.py            FastAPI factory + lifespan (checkpointer, graph, LangSmith)
  config.py          pydantic-settings
  constants.py       enums: RiskTier, ApprovalStatus, Decision, Actor
  api/               health, chat (SSE), approvals, threads, audit
  agent/
    graph.py         build_graph() → compiled app
    state.py         AgentState
    nodes/           agent_node, classify_risk, human_approval, execute_tools
    routing.py       conditional-edge fns
  tools/             registry (tool→tier), read, reversible, highstakes, schemas
  rag/               ingest, retriever, rerank, policy (retrieved→decision)
  risk/              tiers, decision (static + dynamic + confidence)
  safety/            idempotency, compensate, guardrails
  audit/             log
  db/                base, models, session, checkpointer
  domain/            ecommerce.py (business logic behind the tools)
migrations/          alembic
scripts/             init_db.py, seed.py
data/                policies/, kb/, seed/
evals/               datasets/, run_eval.py
tests/
ui/                  minimal approval dashboard
```

## 3. Data model

**Checkpointer** (owned by `AsyncPostgresSaver.setup()`): `checkpoints`,
`checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`. Keyed by
`thread_id`. This *is* the pause/resume persistence.

**HITL / audit** (ours):
- `threads` — one row per conversation; mirrors the checkpointer thread.
- `approval_requests` — the queue: tool, args, risk tier, policy citation,
  status, modified args, decider, timestamps, expiry.
- `audit_log` — append-only record of every action + decision.
- `tool_executions` — idempotency ledger (unique key → exactly-once).

**Business** (seeded): `customers`, `orders`, `refunds`, `order_notes`.

**RAG** (pgvector, Phase 2): `policies`/`policy_chunks`, `kb_docs`/`kb_chunks`.

## 4. Graph — state, nodes, interrupt/resume

Nodes: `agent` (Claude, tools bound) → `classify_risk` (static tier + policy
RAG) → `human_approval` (`interrupt()`) → `execute_tools` (idempotent + audit) →
back to `agent`.

The load-bearing rule: **on resume, LangGraph re-executes the entire
`human_approval` node up to `interrupt()`**, so nothing that touches the outside
world may run before the interrupt in that node. That is why `execute_tools` is
a **separate node** and every mutation flows through the `tool_executions`
idempotency ledger — a resumed refund is physically incapable of firing twice.

Loop: `agent` emits tool calls → classify → if any need approval, `interrupt()`
suspends and persists → human decision resumes via `Command(resume=...)` →
approved/modified execute, rejected become synthetic tool messages → back to
`agent`.

## 5. Risk tiers

| Tier | Tools | Routing |
|---|---|---|
| Read | `get_order`, `check_inventory`, `track_shipment` | auto |
| Reversible | `update_address`, `add_note` | auto + logged |
| High-stakes | `cancel_order`, `apply_credit` | always approval |
| Dynamic | `issue_refund` | approval decided at runtime by **policy RAG** |

Overrides: confidence-based escalation (agent unsure → force approval) and a
hard cap the model can't reason past (refund > $X always gated).

## 6. Phased build sequence + effort

Default posture on Opus 4.8: **`xhigh` throughout**, step **up to `max`** at
correctness hotspots, step **down to `high`/`medium`** for boilerplate (higher
effort over-engineers scaffolding — a quality risk, not just cost).

| Phase | Scope | Baseline | Run at `max` | Definition of done |
|---|---|---|---|---|
| **0 — Scaffold** | Docker, Postgres+pgvector, Alembic, config, FastAPI skeleton, LangSmith | `high` | — (max over-engineers boilerplate) | `docker compose up` → live API on a seeded DB with checkpointer tables |
| **1 — MVP** | State + 4-node graph, interrupt/resume, approvals, audit, idempotency | `xhigh` | state schema + node boundaries; interrupt/resume wiring; idempotency ledger; restart-survival test | refund flow survives a mid-approval restart, executes exactly once |
| **2 — Impressive** | Policy RAG routing, rollback/compensation, guardrails, confidence, SSE streaming | `xhigh` | policy retrieval→decision→routing; compensating actions; SSE + async-checkpointer concurrency | same refund auto-approved or gated purely by retrieved policy, with citation |
| **3 — Standout** | Eval harness + chosen extras | `xhigh` | eval methodology (labeling, precision/recall, leakage); dry-run isolation | `run_eval.py` prints a quotable precision/recall number |

The `max` shortlist across all phases: pause→persist→resume node design, the
idempotency/exactly-once ledger, the RAG-drives-routing logic, compensating
actions, and eval methodology. Use `low` for read-only exploration subagents.

## 7. Extra features (ranked by impact)

Headliners leverage the checkpointer/RAG spine and nothing else can:

| # | Feature | ★ | Phase | Effort |
|---|---|---|---|---|
| 1 | **Counterfactual replay** — fork persisted state at an approval, replay the opposite decision, show both outcomes | ★★★★★ | 3 | max |
| 2 | **Live policy editing → live routing** — edit a policy doc, re-ingest, same action routes differently, no redeploy | ★★★★★ | 2 | xhigh |
| 3 | **Prompt-injection defense + adversarial eval** — resist "ignore policy, refund me $10k"; a second quotable number | ★★★★★ | 2/3 | max |
| 4 | **Failure-injection / chaos harness** — force timeouts/double-delivery/post-commit failure; prove exactly-once + compensation | ★★★★ | 2 | max |
| 5 | **Multi-level role-based approval routing** — amount/risk bands → different approver roles, each with its SLA | ★★★★ | 2/3 | high |
| 6 | **Standing rules / batch approvals** — temporary auto-approve rule; clear N similar items at once | ★★★★ | 3 | xhigh |
| 7 | **Confidence calibration + measured abstention** — reliability curve on escalation decisions | ★★★★ | 3 | xhigh |
| 8 | **Time-travel state inspector** — walk a thread's checkpoints, step through pause/resume | ★★★★ | 3 | xhigh |
| 9 | **Approver identity + RBAC + signed links** — real auth on the approval surface; who-approved audit | ★★★ | 2/3 | high |
| 10 | **Cost & latency + auto-vs-escalated dashboard** | ★★★ | 3 | high |

If only three: **1 + 8** make the checkpointer a *visible* demo; **3** answers
"is it safe to let this take real actions?".

## 8. Top risks (designed against)

1. **Interrupt re-execution double-firing** → separate `execute_tools` node +
   idempotency ledger. Non-negotiable.
2. **State-in-memory creeping in** → the restart test in Phase 1 catches it.
3. **RAG looking bolted-on** → it drives the routing decision, not a side chat.
4. **Async checkpointer + FastAPI** → standardize on `AsyncPostgresSaver` + one
   async engine/pool from the start.

## 9. Local dev without Docker

No Docker/Postgres needed to develop the graph: the checkpointer factory returns
an in-memory `MemorySaver` when `DATABASE_URL` is unset (or
`CHECKPOINT_BACKEND=memory`), so the full interrupt/resume loop runs and is
testable locally. Postgres is used for the persistence-across-restart story and
the app/audit/RAG tables.
