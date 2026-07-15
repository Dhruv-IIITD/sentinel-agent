"""Dev convenience: create the pgvector extension and all app tables.

For production use Alembic migrations instead
(`alembic revision --autogenerate` → `alembic upgrade head`). This script is the
fast path for local iteration once a Postgres is up.

    PYTHONPATH=src python scripts/init_db.py
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.db import models  # noqa: F401  (registers tables on Base.metadata)
from app.db.base import Base
from app.db.session import db_available, get_engine


async def main() -> None:
    if not db_available():
        raise SystemExit("DATABASE_URL is not set — nothing to initialize.")
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("init_db: pgvector extension ensured + app tables created.")


if __name__ == "__main__":
    asyncio.run(main())
