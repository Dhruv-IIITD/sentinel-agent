"""Counterfactual replay — play out *both* decisions as separate live branches.

Because the entire graph state is checkpointed, a paused approval can be forked:
we seed a fresh thread from the paused state (via `aupdate_state` as the
classify_risk output), run it to the interrupt, and resume it once with "approve"
and once with "reject". Each branch runs on a **cloned sandbox store**, so both
are real graph executions (real model follow-up) that mutate nothing real — the
original thread stays exactly where it was.

Only stores that can `clone()` (the in-memory store) support this; a Postgres
sandbox would need a rollback-scoped session per branch.
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from .graph import build_graph


def _last_reply(messages: list) -> str:
    for m in reversed(messages):
        if getattr(m, "type", None) == "ai" and not getattr(m, "tool_calls", None):
            return m.content or ""
    return (messages[-1].content if messages else "") or ""


def _effects(original, sandbox) -> dict:
    out = {}
    for attr in ("refunds", "credits", "notes"):
        before, after = len(getattr(original, attr)), len(getattr(sandbox, attr))
        if before != after:
            out[attr] = {"before": before, "after": after}
    return out


async def run_counterfactual(
    base_graph,
    thread_id: str,
    *,
    store,
    model_factory,
    policy,
    hard_cap: float,
    confidence_threshold: float,
    decisions: tuple[str, ...] = ("approve", "reject"),
) -> dict:
    if not hasattr(store, "clone"):
        return {"error": "counterfactual replay requires a cloneable (in-memory) store"}

    base = await base_graph.aget_state({"configurable": {"thread_id": thread_id}})
    values = base.values or {}
    plans = values.get("plans") or []
    if not base.interrupts or not plans:
        return {"error": "thread is not paused at an approval"}

    outcomes: dict[str, dict] = {}
    for decision in decisions:
        sandbox = store.clone()
        fork = build_graph(
            MemorySaver(), sandbox, model_factory(),
            policy=policy, hard_cap=hard_cap, confidence_threshold=confidence_threshold,
        )
        cfg = {"configurable": {"thread_id": f"{thread_id}::cf::{decision}"}}
        # Seed the branch at the classify_risk output, then run it to the interrupt.
        await fork.aupdate_state(
            cfg,
            {
                "messages": values.get("messages", []),
                "plans": plans,
                "decisions": {},
                "user_id": values.get("user_id", ""),
                "confidence": 1.0,
            },
            as_node="classify_risk",
        )
        await fork.ainvoke(None, cfg)  # reach the interrupt
        resume = {p["id"]: {"decision": decision, "decided_by": "counterfactual"}
                  for p in plans if p["needs_approval"]}
        result = await fork.ainvoke(Command(resume=resume), cfg)
        outcomes[decision] = {
            "reply": _last_reply(result.get("messages", [])),
            "effects": _effects(store, sandbox),
        }

    return {
        "thread_id": thread_id,
        "action": {"tool": plans[0]["name"], "args": plans[0]["args"]},
        "outcomes": outcomes,
    }
