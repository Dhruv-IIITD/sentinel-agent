"""Async SQLAlchemy engine + session management.

The engine is created lazily and cached, so importing this module never touches
a database. When ``DATABASE_URL`` is unset, `db_available()` is False and the
app runs with the in-memory checkpointer (dev mode).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from ..config import settings


def db_available() -> bool:
    return settings.database_configured


@lru_cache
def get_engine() -> AsyncEngine:
    if not settings.database_configured:
        raise RuntimeError(
            "DATABASE_URL is not set — no SQLAlchemy engine available. "
            "Set it, or run in memory-checkpointer dev mode."
        )
    return create_async_engine(
        settings.sqlalchemy_async_url,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional scope: commit on success, roll back on error."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session (no implicit commit)."""
    async with get_sessionmaker()() as session:
        yield session
