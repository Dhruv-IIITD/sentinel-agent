"""Audit log — every action and decision."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..auth.deps import get_current_user

router = APIRouter(tags=["audit"], dependencies=[Depends(get_current_user)])


@router.get("/audit")
async def get_audit(request: Request, thread_id: str | None = None, limit: int = 100) -> list[dict]:
    return await request.app.state.store.list_audit(thread_id=thread_id, limit=limit)
