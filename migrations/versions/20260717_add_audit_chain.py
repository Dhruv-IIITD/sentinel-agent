"""Add and backfill the tamper-evident audit hash chain.

Revision ID: 20260717_add_audit_chain
Revises: 20260716_add_payments
Create Date: 2026-07-17
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260717_add_audit_chain"
down_revision: str | None = "20260716_add_payments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _chain_hash(prev_hash: str | None, row: dict) -> str:
    canonical = json.dumps(row, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(((prev_hash or "GENESIS") + canonical).encode()).hexdigest()


def upgrade() -> None:
    op.add_column("audit_log", sa.Column("prev_hash", sa.String(length=64), nullable=True))
    op.add_column("audit_log", sa.Column("entry_hash", sa.String(length=64), nullable=True))

    audit_log = sa.table(
        "audit_log",
        sa.column("id", sa.Integer()),
        sa.column("thread_id", sa.String()),
        sa.column("event_type", sa.String()),
        sa.column("actor", sa.String()),
        sa.column("tool_name", sa.String()),
        sa.column("args", sa.JSON()),
        sa.column("result", sa.JSON()),
        sa.column("idempotency_key", sa.String()),
        sa.column("policy_ref", sa.Text()),
        sa.column("latency_ms", sa.Integer()),
        sa.column("tokens", sa.Integer()),
        sa.column("created_at", sa.TIMESTAMP(timezone=True)),
        sa.column("prev_hash", sa.String()),
        sa.column("entry_hash", sa.String()),
    )
    content_columns = [
        audit_log.c.id,
        audit_log.c.thread_id,
        audit_log.c.event_type,
        audit_log.c.actor,
        audit_log.c.tool_name,
        audit_log.c.args,
        audit_log.c.result,
        audit_log.c.idempotency_key,
        audit_log.c.policy_ref,
        audit_log.c.latency_ms,
        audit_log.c.tokens,
        audit_log.c.created_at,
    ]

    connection = op.get_bind()
    rows = connection.execute(
        sa.select(*content_columns).order_by(audit_log.c.id)
    ).mappings().all()
    prev_hash = None
    for row in rows:
        content = dict(row)
        entry_hash = _chain_hash(prev_hash, content)
        connection.execute(
            audit_log.update()
            .where(audit_log.c.id == row["id"])
            .values(prev_hash=prev_hash, entry_hash=entry_hash)
        )
        prev_hash = entry_hash

    op.alter_column("audit_log", "entry_hash", nullable=False)


def downgrade() -> None:
    op.drop_column("audit_log", "entry_hash")
    op.drop_column("audit_log", "prev_hash")
