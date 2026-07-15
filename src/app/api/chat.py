"""Chat endpoint — drive the agent graph for one user message.

Runs the graph to the next stop. If it paused at the approval node, this
persists an `approval_requests` row per pending action (the dashboard's queue)
and returns ``awaiting_approval``. Otherwise it returns the agent's reply.

Persisting the approval row here — rather than inside the graph's approval node —
is deliberate: that node re-executes on resume, so keeping DB writes out of it
avoids double-inserts.

(Phase 2 adds an SSE streaming variant; Phase 1 returns a single JSON response.)
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Request
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from .serialization import last_reply

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None
    user_id: str = "anonymous"


def _initial_state(req: ChatRequest) -> dict:
    return {
        "messages": [HumanMessage(req.message)],
        "plans": [],
        "decisions": {},
        "user_id": req.user_id,
        "confidence": 1.0,
    }


async def finalize(graph, store, thread_id: str, cfg: dict, result: dict) -> dict:
    """Shape a graph result into a chat response, persisting approvals if paused."""
    interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
    if interrupts:
        items = interrupts[0].value  # list of pending approval items
        state = await graph.aget_state(cfg)
        checkpoint_id = (state.config.get("configurable") or {}).get("checkpoint_id")
        await store.create_approvals(thread_id, checkpoint_id, items)
        pending = await store.list_approvals(status="pending", thread_id=thread_id)
        return {"thread_id": thread_id, "status": "awaiting_approval", "approvals": pending}

    return {
        "thread_id": thread_id,
        "status": "completed",
        "reply": last_reply(result.get("messages", [])),
    }


@router.post("/chat")
async def chat(req: ChatRequest, request: Request) -> dict:
    graph = request.app.state.graph
    store = request.app.state.store
    thread_id = req.thread_id or uuid.uuid4().hex
    cfg = {"configurable": {"thread_id": thread_id}}
    result = await graph.ainvoke(_initial_state(req), cfg)
    return await finalize(graph, store, thread_id, cfg, result)


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request) -> EventSourceResponse:
    """Server-Sent Events: a live trace of the agent's steps, then a terminal
    ``approval_required`` or ``message`` event."""
    graph = request.app.state.graph
    store = request.app.state.store
    thread_id = req.thread_id or uuid.uuid4().hex
    cfg = {"configurable": {"thread_id": thread_id}}

    async def gen():
        yield {"event": "start", "data": json.dumps({"thread_id": thread_id})}
        async for chunk in graph.astream(_initial_state(req), cfg, stream_mode="updates"):
            for node, update in chunk.items():
                if node.startswith("__"):  # e.g. __interrupt__ — handled after the loop
                    continue
                payload: dict = {"node": node}
                if isinstance(update, dict):
                    if update.get("plans"):
                        payload["plans"] = [
                            {"tool": p["name"], "tier": p["tier"], "needs_approval": p["needs_approval"]}
                            for p in update["plans"]
                        ]
                    msgs = update.get("messages") or []
                    if msgs:
                        last = msgs[-1]
                        if getattr(last, "tool_calls", None):
                            payload["tool_calls"] = [tc["name"] for tc in last.tool_calls]
                        elif getattr(last, "content", None):
                            payload["content"] = last.content
                yield {"event": "step", "data": json.dumps(payload)}

        snapshot = await graph.aget_state(cfg)
        if snapshot.interrupts:
            items = snapshot.interrupts[0].value
            checkpoint_id = (snapshot.config.get("configurable") or {}).get("checkpoint_id")
            await store.create_approvals(thread_id, checkpoint_id, items)
            pending = await store.list_approvals(status="pending", thread_id=thread_id)
            yield {"event": "approval_required", "data": json.dumps({"approvals": pending})}
        else:
            reply = last_reply((snapshot.values or {}).get("messages", []))
            yield {"event": "message", "data": json.dumps({"reply": reply})}
        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(gen())
