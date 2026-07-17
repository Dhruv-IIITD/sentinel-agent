"""FastAPI application factory + lifespan wiring.

Lifespan owns the long-lived resources — the LangGraph checkpointer (and, from
Phase 1, the compiled graph) — and exposes them on ``app.state``. LangSmith
tracing env vars are set here when enabled.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .agent.graph import build_graph
from .agent.llm import get_model
from .auth.users import build_user_store
from .config import settings
from .db.checkpointer import checkpointer_context
from .domain.ecommerce import build_store
from .events import build_event_bus
from .payments import build_payment_provider
from .rag.policy import build_policy_engine
from .safety.ratelimit import RateLimitMiddleware, build_rate_limiter
from .safety.verification import build_verification_store
from .sla import sweep

# Routers
from .api.audit import router as audit_router
from .api.auth import router as auth_router
from .api.approvals import router as approvals_router
from .api.catalog import router as catalog_router
from .api.chat import router as chat_router
from .api.compensate import router as compensate_router
from .api.counterfactual import router as counterfactual_router
from .api.health import router as health_router
from .api.metrics import router as metrics_router
from .api.threads import router as threads_router
from .api.voice import router as voice_router
from .api.ws import router as ws_router

logger = logging.getLogger(__name__)


def _configure_langsmith() -> None:
    if settings.langsmith_tracing and settings.langsmith_api_key:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project


async def _sla_loop(store, event_bus, sla_seconds: int, poll_seconds: int) -> None:
    """Run SLA sweeps in the background without becoming an API dependency."""
    while True:
        await asyncio.sleep(max(1, poll_seconds))
        try:
            await sweep(
                store,
                event_bus,
                sla_seconds,
                now=datetime.now(timezone.utc),
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the background safety net is non-fatal
            logger.exception("approval SLA sweep failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_langsmith()
    if settings.auth_enabled and not settings.jwt_secret:
        raise RuntimeError("JWT_SECRET is required when AUTH_ENABLED is true")
    async with checkpointer_context(settings) as checkpointer:
        payments = build_payment_provider(settings)
        store = build_store(settings, payments=payments)
        policy = build_policy_engine()
        event_bus = build_event_bus(settings)
        verification = build_verification_store(settings)
        rate_limiter = build_rate_limiter(settings)
        users = build_user_store(settings.demo_user_password)
        app.state.settings = settings
        app.state.checkpointer = checkpointer
        app.state.store = store
        app.state.payments = payments
        app.state.policy = policy
        app.state.event_bus = event_bus
        app.state.verification = verification
        app.state.rate_limiter = rate_limiter
        app.state.users = users
        # Fresh model per counterfactual branch (the real model is stateless, so
        # returning the cached instance is fine); tests override this factory.
        app.state.model_factory = get_model
        # model=None -> real ChatAnthropic (constructed lazily on first turn)
        app.state.graph = build_graph(
            checkpointer, store, policy=policy, hard_cap=settings.hard_refund_cap
        )
        sla_task = None
        if settings.sla_seconds > 0:
            sla_task = asyncio.create_task(
                _sla_loop(store, event_bus, settings.sla_seconds, settings.sla_poll_seconds),
                name="approval-sla-sweep",
            )
        try:
            yield
        finally:
            if sla_task is not None:
                sla_task.cancel()
                await asyncio.gather(sla_task, return_exceptions=True)
            for resource in (event_bus, verification, rate_limiter):
                close = getattr(resource, "aclose", None)
                if close is not None:
                    await close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="HITL Agent",
        version="0.1.0",
        summary="Human-in-the-loop tool-using agent with pause/persist/resume.",
        lifespan=lifespan,
    )
    app.add_middleware(RateLimitMiddleware)
    app.include_router(auth_router)
    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(approvals_router)
    app.include_router(compensate_router)
    app.include_router(counterfactual_router)
    app.include_router(threads_router)
    app.include_router(audit_router)
    app.include_router(voice_router)
    app.include_router(metrics_router)
    app.include_router(catalog_router)
    app.include_router(ws_router)

    # The console. Prefer the built React app (`make web` -> web/dist); fall back to
    # the dependency-free `ui/` dashboard when the frontend hasn't been built, so the
    # API is never left without a UI (CI, a bare checkout, a Python-only deploy).
    root = Path(__file__).resolve().parents[2]
    console_dir = next((d for d in (root / "web" / "dist", root / "ui") if d.is_dir()), None)
    if console_dir is not None:
        app.mount("/ui", StaticFiles(directory=str(console_dir), html=True), name="ui")

        @app.get("/", include_in_schema=False)
        async def _root() -> RedirectResponse:
            return RedirectResponse(url="/ui/")

    return app


app = create_app()
