"""Checkpointer factory — the persistence that makes pause/resume survivable.

Postgres in production (state survives restarts), in-memory for dev/tests (the
full interrupt/resume loop still runs, it just doesn't outlive the process).
Both are entered as an async context manager so the Postgres connection pool is
owned for the app/test lifetime.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import os

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from ..config import Settings, settings as default_settings


@asynccontextmanager
async def checkpointer_context(
    settings: Settings = default_settings,
) -> AsyncIterator[BaseCheckpointSaver]:
    """Yield a checkpointer for the configured backend.

    - postgres: state survives across processes (production).
    - sqlite:   state survives across processes via a local file (no Postgres).
    - memory:   in-process only (dev/tests).

    Usage:
        async with checkpointer_context() as cp:
            graph = build_graph(cp, store)
    """
    backend = settings.resolved_checkpoint_backend
    if backend == "postgres":
        async with AsyncPostgresSaver.from_conn_string(settings.psycopg_conninfo) as saver:
            await saver.setup()  # idempotent: creates checkpoint tables if absent
            yield saver
    elif backend == "sqlite":
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        directory = os.path.dirname(settings.sqlite_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(settings.sqlite_path) as saver:
            await saver.setup()  # idempotent
            yield saver
    else:
        yield MemorySaver()
