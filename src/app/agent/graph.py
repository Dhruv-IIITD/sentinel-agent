"""Assemble the compiled LangGraph app.

    agent ──tool_calls?──▶ classify_risk ──needs approval?──▶ human_approval
      ▲                         │ no                              │ interrupt()/resume
      │                         ▼                                 ▼
      └──────────────────── execute_tools ◀────────────────────── (approved/modified/rejected)

`build_graph` injects its dependencies (checkpointer, store, model) so the same
graph runs against Postgres+Claude in production and MemoryStore+a fake model in
tests.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ..config import settings
from .nodes.agent_node import make_agent_node
from .nodes.classify_risk import make_classify_risk
from .nodes.execute_tools import make_execute_tools
from .nodes.human_approval import make_human_approval
from .routing import route_after_agent, route_after_classify
from .state import AgentState


def build_graph(checkpointer, store, model=None, policy=None, hard_cap=None, confidence_threshold=None):
    if policy is None:
        from ..rag.policy import build_policy_engine

        policy = build_policy_engine()
    if hard_cap is None:
        hard_cap = settings.hard_refund_cap
    if confidence_threshold is None:
        confidence_threshold = settings.confidence_threshold

    g = StateGraph(AgentState)
    g.add_node("agent", make_agent_node(model))
    g.add_node("classify_risk", make_classify_risk(
        store=store, policy=policy, hard_cap=hard_cap, confidence_threshold=confidence_threshold,
    ))
    g.add_node("human_approval", make_human_approval())
    g.add_node("execute_tools", make_execute_tools(store))

    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route_after_agent, {"classify_risk": "classify_risk", END: END})
    g.add_conditional_edges(
        "classify_risk",
        route_after_classify,
        {"human_approval": "human_approval", "execute_tools": "execute_tools"},
    )
    g.add_edge("human_approval", "execute_tools")
    g.add_edge("execute_tools", "agent")

    return g.compile(checkpointer=checkpointer)
