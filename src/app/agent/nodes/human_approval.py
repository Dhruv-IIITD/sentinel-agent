"""The approval node — where the graph pauses.

`interrupt(payload)` suspends the graph and persists its entire state; the
resume value (supplied via ``Command(resume=...)``) becomes the human's decision.

CRITICAL: on resume, LangGraph re-executes this node from the top up to the
`interrupt()` call, so everything before it must be side-effect-free. Building
the payload is pure. Persisting the approval-request row for the dashboard is
the API layer's responsibility, deliberately *not* done here.
"""

from __future__ import annotations

from langgraph.types import interrupt

from ..state import AgentState


def _payload(plan: dict) -> dict:
    return {
        "tool_call_id": plan["id"],
        "tool": plan["name"],
        "args": plan["args"],
        "risk_tier": plan["tier"],
        "justification": plan["reason"],
    }


def make_human_approval():
    async def human_approval(state: AgentState) -> dict:
        decisions = dict(state.get("decisions") or {})
        pending = [
            p for p in (state.get("plans") or [])
            if p["needs_approval"] and p["id"] not in decisions
        ]
        if not pending:
            return {}
        resumed = interrupt([_payload(p) for p in pending])  # <-- pause / persist / resume
        if isinstance(resumed, dict):
            decisions.update(resumed)
        return {"decisions": decisions}

    return human_approval
