"""pgvector-backed policy chunk table (production vector index).

Kept on a SEPARATE declarative base so it never enters the app's `Base.metadata`
— the `Vector` column is Postgres-only and would break SQLite create_all in
tests. `scripts/ingest_policies.py` owns creating this table + the extension.
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..config import settings


class RagBase(DeclarativeBase):
    pass


class PolicyChunk(RagBase):
    __tablename__ = "policy_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(200), default="")
    section: Mapped[str] = mapped_column(String(300), default="")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(settings.embedding_dim))
