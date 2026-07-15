"""Compensation endpoint — roll back a previously executed side effect.

Keyed by the idempotency key (surfaced on `executed` audit rows), so the same
ledger entry that guaranteed exactly-once also anchors the rollback.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(tags=["compensate"])


class CompensateRequest(BaseModel):
    actor: str = "manager"
    reason: str = ""


@router.post("/compensate/{idempotency_key}")
async def compensate(idempotency_key: str, body: CompensateRequest, request: Request) -> dict:
    result = await request.app.state.store.compensate(
        idempotency_key, actor=body.actor, reason=body.reason
    )
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result
