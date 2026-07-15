"""Conditional-edge functions for the graph."""

from __future__ import annotations

from langgraph.graph import END

from .state import AgentState


def route_after_agent(state: AgentState) -> str:
    """If the model requested tools, classify them; otherwise the turn is done."""
    messages = state.get("messages") or []
    last = messages[-1] if messages else None
    if last is not None and getattr(last, "tool_calls", None):
        return "classify_risk"
    return END


def route_after_classify(state: AgentState) -> str:
    """Gate to human approval iff some planned action needs an undecided approval."""
    decisions = state.get("decisions") or {}
    for plan in state.get("plans") or []:
        if plan["needs_approval"] and plan["id"] not in decisions:
            return "human_approval"
    return "execute_tools"
