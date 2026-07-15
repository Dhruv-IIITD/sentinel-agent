"""Helpers to turn LangChain messages / graph results into JSON responses."""

from __future__ import annotations


def last_reply(messages: list) -> str:
    """The agent's final natural-language reply (last AI message without tool calls)."""
    for m in reversed(messages):
        if getattr(m, "type", None) == "ai" and not getattr(m, "tool_calls", None):
            return m.content or ""
    return (messages[-1].content if messages else "") or ""


def serialize_message(m) -> dict:
    return {
        "role": getattr(m, "type", None),
        "content": m.content,
        "tool_calls": getattr(m, "tool_calls", None) or None,
    }
