# Observability (LangSmith)

Every graph run is traceable end to end — each node (`agent`, `classify_risk`,
`human_approval`, `execute_tools`), every tool call, every policy retrieval, and
each LLM call with its token count, cost, and latency.

## Enable it

Set these in `.env` (see `.env.example`):

```
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=ls-...
LANGSMITH_PROJECT=hitl-agent
```

The app wires these into the process environment on startup (see
`_configure_langsmith` in [`src/app/main.py`](../src/app/main.py)); LangChain /
LangGraph pick them up automatically. With tracing off (the default), there is
zero overhead and no network calls.

## What to look for in a trace

- **The pause/resume seam** — a run that stops at `human_approval` (an interrupt),
  and a later run on the same `thread_id` that resumes from it. Two traces, one
  conversation.
- **Policy-driven routing** — the `classify_risk` span shows the retrieved policy
  clause and the resulting approve/auto decision.
- **Cost & latency** — per-node and per-thread token usage and wall-clock, which
  is the raw material for a "% auto vs escalated" and cost-per-conversation
  dashboard.

## Correlating with the audit log

Every side effect is also recorded in the app's own audit log (`GET /audit`,
redacted for PII) and the idempotency ledger. LangSmith answers "what did the
agent think?"; the audit log answers "what did it *do*, and was it exactly once?".
Together they give a full, reviewable account of each action.
```
