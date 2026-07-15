"""SQLAlchemy declarative base + shared column types.

`JSONB_` maps to native ``JSONB`` on Postgres and falls back to generic ``JSON``
on other dialects (e.g. SQLite in tests), so the same models run in both.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, TIMESTAMP, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names → clean Alembic autogenerate diffs.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# JSONB on Postgres, JSON everywhere else.
JSONB_ = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Adds a server-side ``created_at`` (UTC)."""

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
