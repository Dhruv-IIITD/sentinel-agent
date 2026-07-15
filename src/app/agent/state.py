"""The graph's state schema.

`messages` uses the standard ``add_messages`` reducer (append). Everything else
is turn-scoped scratch that the checkpointer persists alongside the messages, so
it survives the pause at the approval node.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class ToolPlan(TypedDict):
    """One classified tool call for the current turn."""

    id: str  # the LLM tool_call id — stable across resume, used as the idempotency anchor
    name: str
    args: dict
    tier: str
    needs_approval: bool
    reason: str  # justification (Phase 2: the retrieved policy citation)


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    plans: list[ToolPlan]
    # tool_call_id -> {"decision": approve|reject|modify, "modified_args"?, "reason"?, "decided_by"?}
    decisions: dict[str, dict]
    user_id: str
    # Agent self-reported confidence for the current turn (1.0 = certain).
    confidence: float
