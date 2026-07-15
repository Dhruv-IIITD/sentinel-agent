"""The reasoning node — calls Claude with the tools bound.

The model is a dependency (injected by `build_graph`) so tests can pass a fake
and never hit the network.
"""

from __future__ import annotations

from langchain_core.messages import SystemMessage

from ...tools.registry import langchain_tools
from ..llm import get_model
from ..prompts import SYSTEM_PROMPT
from ..state import AgentState


def make_agent_node(model=None):
    async def agent_node(state: AgentState) -> dict:
        m = model if model is not None else get_model()
        bound = m.bind_tools(langchain_tools())
        messages = [SystemMessage(content=SYSTEM_PROMPT), *state["messages"]]
        response = await bound.ainvoke(messages)
        # Optional self-reported confidence (prod: parsed/structured; tests: additional_kwargs).
        confidence = float((getattr(response, "additional_kwargs", None) or {}).get("confidence", 1.0))
        return {"messages": [response], "confidence": confidence}

    return agent_node
