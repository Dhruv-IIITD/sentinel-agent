"""Policy retriever.

`KeywordRetriever` is a dependency-free lexical retriever over the policy chunks —
deterministic, so routing decisions are reproducible and testable without an
external embedding API. It is the default and works in production too.

For semantic recall at scale, `PgVectorRetriever` (embeddings + pgvector) is the
drop-in upgrade behind the same `search()` contract; it is a documented stub here
because this environment has no embeddings provider.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Hit:
    text: str
    section: str
    source: str
    score: float


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9$]+", s.lower()))


class PolicyRetriever(Protocol):
    def search(self, query: str, k: int = 3) -> list[Hit]: ...


class KeywordRetriever:
    def __init__(self, chunks: list[dict]) -> None:
        self.chunks = chunks

    def search(self, query: str, k: int = 3) -> list[Hit]:
        q = _tokens(query)
        scored: list[tuple[int, dict]] = []
        for c in self.chunks:
            overlap = len(q & _tokens(c["text"] + " " + c.get("section", "")))
            if overlap:
                scored.append((overlap, c))
        scored.sort(key=lambda pair: -pair[0])
        return [Hit(c["text"], c.get("section", ""), c.get("source", ""), float(s)) for s, c in scored[:k]]


class VectorRetriever:
    """In-memory cosine retriever over embedded chunks (dev/CI, embedder-agnostic)."""

    def __init__(self, chunks: list[dict], embedder) -> None:
        from .embeddings import cosine

        self._cosine = cosine
        self.embedder = embedder
        self.chunks = chunks
        self.vectors = [embedder.embed(c["text"] + " " + c.get("section", "")) for c in chunks]

    def search(self, query: str, k: int = 3) -> list[Hit]:
        q = self.embedder.embed(query)
        scored = sorted(
            ((self._cosine(q, v), c) for v, c in zip(self.vectors, self.chunks)),
            key=lambda pair: -pair[0],
        )
        return [
            Hit(c["text"], c.get("section", ""), c.get("source", ""), float(s))
            for s, c in scored[:k] if s > 0
        ]


class PgVectorRetriever:  # pragma: no cover - requires Postgres + ingested chunks
    """Semantic retriever over the `policy_chunks` table (embeddings + pgvector).

    The scale path: chunks are embedded once by `scripts/ingest_policies.py`, and
    each query is embedded and ranked by `embedding <=> :q` in the database. Uses
    a sync session to keep the `search()` contract synchronous.
    """

    def __init__(self, embedder, settings) -> None:
        self.embedder = embedder
        self.settings = settings
        self._engine = None

    def _engine_(self):
        if self._engine is None:
            from sqlalchemy import create_engine

            self._engine = create_engine(self.settings.sqlalchemy_sync_url, pool_pre_ping=True)
        return self._engine

    def search(self, query: str, k: int = 3) -> list[Hit]:
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from ..db.rag_models import PolicyChunk

        qv = self.embedder.embed(query)
        with Session(self._engine_()) as s:
            rows = s.scalars(
                select(PolicyChunk).order_by(PolicyChunk.embedding.cosine_distance(qv)).limit(k)
            ).all()
            return [Hit(r.text, r.section, r.source, 1.0) for r in rows]


def build_retriever(chunks: list[dict], settings) -> PolicyRetriever:
    """Pick a retriever from config: keyword (default) or vector."""
    if getattr(settings, "retriever", "keyword") == "vector":
        from .embeddings import HashingEmbedder

        embedder = HashingEmbedder(dim=settings.embedding_dim)
        if settings.database_configured:
            return PgVectorRetriever(embedder, settings)
        return VectorRetriever(chunks, embedder)
    return KeywordRetriever(chunks)
