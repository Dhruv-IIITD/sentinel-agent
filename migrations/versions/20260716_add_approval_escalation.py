"""Add durable approval escalation timestamp.

Revision ID: 20260716_add_approval_escalation
Revises: 20260716_add_products
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260716_add_approval_escalation"
down_revision: str | None = "20260716_add_products"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "approval_requests",
        sa.Column("escalated_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("approval_requests", "escalated_at")
