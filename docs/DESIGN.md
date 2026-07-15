# HITL Agent — Design Brief

Full design context for the Human-in-the-Loop tool-using agent. This is the
source of truth carried over from the ideation conversation. A fresh session can
read this and continue straight into planning.

---

## 1. The idea

An agentic AI system that chats with a user in natural language, answers
questions, looks things up, and **takes real, side-effecting actions** — but
routes high-stakes actions through a human for approval before executing.

The defining feature is **pause → persist → resume**: the graph stops
mid-execution, saves its entire state to a database, and resumes from the exact
same state minutes or days later — even after a server restart. Almost nobody
builds this; it's what makes the project rare and credible.

Grounding domain (default): **e-commerce customer-support ops**. Generalizes to
IT/DevOps ops, finance approvals, HR, etc.

## 2. Example walkthrough

```
User:  "My order #4471 arrived damaged, I want a refund."

Agent: [tool: get_order(4471)] -> $180, delivered 3 days ago
       [tool: retrieve_policy("damaged refund")] -> "Refunds >$50 require
        manager approval; must be within 30 days of delivery."
       -> $180 > $50, so this needs approval.

       PAUSES. Creates an approval request:
          "Refund $180 to order #4471 (damaged, within policy window).
           Approve / Reject / Modify?"

--- graph is now suspended; state persisted to DB. Could be hours later ---

Manager: Approves (via dashboard or Slack)

Agent: [resumes] [tool: issue_refund(4471, 180)] -> done
       "Your $180 refund is processed, 3-5 business days."
```

The "magic moment" is the pause-persist-resume across the human decision.

## 3. Architecture (LangGraph)

```
        +---------+
   ---> |  agent  | <---------------+   (reasoning: Claude)
        +----+----+                 |
             | decides on a tool    |
        +----v--------+             |
        | classify    | <- risk tier + policy check (RAG)
        | risk of tool|
        +----+--------+
     safe?  / \  risky?
        +--v-+ +v--------------+
        |exec| |  interrupt()  |  pause, persist state
        |tool| |  approval node|
        +--+-+ +---+-----------+
           |       | human: approve / reject / modify
           |   +---v----+
           |   | resume | -> exec (or skip, or exec-modified)
           |   +---+----+
        +--v-------v--+
        |  audit log  | -> every action recorded
        +-------------+
```

Two production-grade pieces:

- **Checkpointer** — LangGraph persistence (Postgres-backed). Lets the graph
  survive the pause. Each conversation is a `thread_id`.
- **`interrupt()` + `Command(resume=...)`** — LangGraph's HITL primitive. The
  graph raises an interrupt at the approval node; the API returns the pending
  action to a human; their decision resumes the exact same graph state.

## 4. Risk-tiered tools (key design idea)

Don't gate everything — classify tools into tiers:

| Tier             | Example tools                              | Behavior                          |
|------------------|--------------------------------------------|-----------------------------------|
| Read (safe)      | get_order, check_inventory, track_shipment | Auto-execute                      |
| Reversible write | update_address, add_note                   | Auto-execute + logged             |
| High-stakes      | issue_refund, cancel_order, apply_credit   | Requires approval                 |
| Dynamic          | anything above a policy threshold          | Approval decided at runtime (RAG) |

## 5. Where RAG fits (it drives control flow — not bolted on)

1. **Policy RAG (the standout use).** Before deciding whether an action needs
   approval, the agent retrieves the relevant policy from a knowledge base. The
   retrieved policy *decides whether to route to HITL* and *justifies* the
   approval request. This fuses RAG + agent + HITL into one loop.
2. **Knowledge-base Q&A.** Informational questions answered from retrieved docs
   with citations — classic RAG, as one capability among many.
3. **Similar-case retrieval.** Pull past resolved tickets to inform handling.

Lead with #1 — it's what makes the project cover RAG *and* agentic HITL as one
coherent system rather than two stapled together.

## 6. Feature roadmap (build in this order)

**MVP (core story)**
- Risk-tiered tools + approval queue (approve / reject / **modify**)
- Full audit log of every action and decision

**Impressive (the resume differentiators)**
- Policy-driven dynamic approval via RAG
- Idempotency + rollback (idempotency keys so a resumed refund never
  double-fires; compensating actions to undo)
- Guardrails (PII redaction, action whitelisting, input validation)
- Confidence-based escalation (agent escalates when *it* is uncertain)
- Streaming + live reasoning trace

**Standout (pick 1-2)**
- Dry-run / simulation mode ("what *would* happen") before executing
- Approval timeouts & delegation (auto-escalate if not approved in N minutes)
- Slack-based approvals
- **Eval harness** — measure how often the agent *correctly* routes to HITL
  (precision/recall on "should this have needed approval"). The sleeper feature:
  turns a subjective demo into a project with a quotable number, e.g.
  "correctly flags 96% of actions needing approval, 4% false-escalation rate."

## 7. Stack

- **LangGraph** — graph, `interrupt()`, checkpointer
- **LangChain** — tools, model + retriever integration
- **Claude (Opus/Sonnet)** — reasoning model
- **FastAPI** — chat endpoint (SSE streaming), approval + resume endpoints
- **Postgres** — checkpointer state + audit log + app data (one DB)
- **pgvector** (or Qdrant) + reranker — policy/KB RAG
- **LangSmith** — tracing/observability
- **Approval surface** — minimal dashboard (Streamlit/small page) first;
  upgrade to Slack later
- **Docker** — packaging

## 8. Open decisions (settle first in the plan)

1. **Domain** — e-commerce support (default) vs. IT/DevOps ops vs. finance.
2. **Approval surface** — minimal web dashboard first vs. straight to Slack.

## 9. What makes this resume-grade (don't skip)

- An **eval number** you can quote (the #1 differentiator vs. everyone's demo)
- Tracing/observability (LangSmith) + a cost & latency story
- A **real graph** with branching/loops/retries — not a linear chain
- Guardrails: input validation, output structure, action safety
- Deployed & Dockerized, CI, clean README with an architecture diagram
- Streaming + caching
