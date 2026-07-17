"""Counterfactual replay endpoint — approve vs reject, side by side."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..agent.counterfactual import run_counterfactual
from ..auth.deps import get_current_user
from ..config import settings

router = APIRouter(tags=["counterfactual"], dependencies=[Depends(get_current_user)])


@router.post("/threads/{thread_id}/counterfactual")
async def counterfactual(thread_id: str, request: Request) -> dict:
    """Fork the paused thread and play out both decisions on sandbox stores.

    Returns each branch's final reply and its (sandboxed) effects, without
    touching the real thread or any real data."""
    app = request.app
    result = await run_counterfactual(
        app.state.graph,
        thread_id,
        store=app.state.store,
        model_factory=app.state.model_factory,
        policy=app.state.policy,
        hard_cap=settings.hard_refund_cap,
        confidence_threshold=settings.confidence_threshold,
    )
    if result.get("error"):
        raise HTTPException(status_code=409, detail=result["error"])
    return result
