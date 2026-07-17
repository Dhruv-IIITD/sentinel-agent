"""Add payment references and provider refund metadata.

Revision ID: 20260716_add_payments
Revises: 20260716_add_approval_escalation
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260716_add_payments"
down_revision: str | None = "20260716_add_approval_escalation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("payment_ref", sa.String(length=255), nullable=True))
    op.add_column("refunds", sa.Column("provider", sa.String(length=40), nullable=True))
    op.add_column(
        "refunds",
        sa.Column("provider_refund_id", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("refunds", "provider_refund_id")
    op.drop_column("refunds", "provider")
    op.drop_column("orders", "payment_ref")
