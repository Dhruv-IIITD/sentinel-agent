"""Thread history — reconstructed from the checkpointer state."""

from __future__ import annotations

from fastapi import APIRouter, Request

from .serialization import serialize_message

router = APIRouter(tags=["threads"])


@router.get("/threads/{thread_id}")
async def get_thread(thread_id: str, request: Request) -> dict:
    graph = request.app.state.graph
    cfg = {"configurable": {"thread_id": thread_id}}
    state = await graph.aget_state(cfg)
    messages = (state.values or {}).get("messages", [])
    return {
        "thread_id": thread_id,
        "messages": [serialize_message(m) for m in messages],
        "awaiting_approval": bool(state.interrupts),
    }


@router.get("/threads/{thread_id}/history")
async def thread_history(thread_id: str, request: Request) -> dict:
    """Time-travel inspector: the thread's checkpoint history (newest first).

    Each entry is a persisted point the graph could resume from — the visible
    face of the pause/persist/resume mechanism."""
    graph = request.app.state.graph
    cfg = {"configurable": {"thread_id": thread_id}}
    checkpoints = []
    async for snap in graph.aget_state_history(cfg):
        checkpoints.append({
            "checkpoint_id": snap.config["configurable"].get("checkpoint_id"),
            "step": (snap.metadata or {}).get("step"),
            "next": list(snap.next),
            "num_messages": len((snap.values or {}).get("messages", [])),
            "interrupted": bool(snap.interrupts),
        })
    return {"thread_id": thread_id, "checkpoints": checkpoints}
