"""FastAPI application factory + lifespan wiring.

Lifespan owns the long-lived resources — the LangGraph checkpointer (and, from
Phase 1, the compiled graph) — and exposes them on ``app.state``. LangSmith
tracing env vars are set here when enabled.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .agent.graph import build_graph
from .agent.llm import get_model
from .config import settings
from .db.checkpointer import checkpointer_context
from .domain.ecommerce import build_store
from .rag.policy import build_policy_engine

# Routers
from .api.audit import router as audit_router
from .api.approvals import router as approvals_router
from .api.catalog import router as catalog_router
from .api.chat import router as chat_router
from .api.compensate import router as compensate_router
from .api.counterfactual import router as counterfactual_router
from .api.health import router as health_router
from .api.metrics import router as metrics_router
from .api.threads import router as threads_router
from .api.voice import router as voice_router


def _configure_langsmith() -> None:
    if settings.langsmith_tracing and settings.langsmith_api_key:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_langsmith()
    async with checkpointer_context(settings) as checkpointer:
        store = build_store(settings)
        policy = build_policy_engine()
        app.state.settings = settings
        app.state.checkpointer = checkpointer
        app.state.store = store
        app.state.policy = policy
        # Which orders each call has proved it owns: {thread_id: {order_id, ...}}.
        # The identity gate reads this — see api/voice.py::_require_verified.
        app.state.verified = {}
        # Fresh model per counterfactual branch (the real model is stateless, so
        # returning the cached instance is fine); tests override this factory.
        app.state.model_factory = get_model
        # model=None -> real ChatAnthropic (constructed lazily on first turn)
        app.state.graph = build_graph(
            checkpointer, store, policy=policy, hard_cap=settings.hard_refund_cap
        )
        yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="HITL Agent",
        version="0.1.0",
        summary="Human-in-the-loop tool-using agent with pause/persist/resume.",
        lifespan=lifespan,
    )
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
