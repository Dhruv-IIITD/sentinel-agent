"""Liveness / readiness endpoint."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from ..config import settings
from ..db.session import db_available, get_engine

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict:
    """Report config and dependency status.

    ``database`` is one of: ``ok`` (reachable), ``error: ...`` (configured but
    unreachable), or ``not-configured`` (dev / in-memory mode).
    """
    if not db_available():
        database = "not-configured"
    else:
        try:
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
            database = "ok"
        except Exception as exc:  # pragma: no cover - depends on live DB
            database = f"error: {exc.__class__.__name__}"

    return {
        "status": "ok",
        "app_env": settings.app_env,
        "model": settings.model,
        "effort": settings.effort,
        "checkpoint_backend": settings.resolved_checkpoint_backend,
        "database": database,
    }
