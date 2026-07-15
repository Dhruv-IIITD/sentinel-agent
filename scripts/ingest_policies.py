"""Embed the policy docs into the pgvector `policy_chunks` table (prod scale path).

    PYTHONPATH=src python scripts/ingest_policies.py

Creates the vector extension + table, then embeds each policy clause with the
configured embedder and upserts it. `PgVectorRetriever` then ranks by cosine
distance in the database. Requires DATABASE_URL and RETRIEVER=vector.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.config import settings
from app.db.session import db_available, get_engine
from app.rag.embeddings import HashingEmbedder
from app.rag.ingest import load_policy_dir
from app.rag.policy import default_policy_dir


async def main() -> None:
    if not db_available():
        raise SystemExit("DATABASE_URL is not set.")

    from app.db.rag_models import PolicyChunk, RagBase

    chunks = load_policy_dir(default_policy_dir())
    embedder = HashingEmbedder(dim=settings.embedding_dim)
    engine = get_engine()

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(RagBase.metadata.create_all)
        await conn.execute(text("TRUNCATE policy_chunks RESTART IDENTITY"))

    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(engine) as s:
        for c in chunks:
            s.add(PolicyChunk(
                source=c.get("source", ""), section=c.get("section", ""), text=c["text"],
                embedding=embedder.embed(c["text"] + " " + c.get("section", "")),
            ))
        await s.commit()
    await engine.dispose()
    print(f"ingest_policies: embedded {len(chunks)} policy chunks into policy_chunks.")


if __name__ == "__main__":
    asyncio.run(main())
