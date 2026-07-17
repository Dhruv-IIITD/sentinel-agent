"""Add products and link orders to the catalog.

Revision ID: 20260716_add_products
Revises:
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260716_add_products"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("emoji", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        sa.UniqueConstraint("sku", name=op.f("uq_products_sku")),
    )
    op.add_column("orders", sa.Column("product_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_orders_product_id_products"),
        "orders",
        "products",
        ["product_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_orders_product_id_products"), "orders", type_="foreignkey")
    op.drop_column("orders", "product_id")
    op.drop_table("products")
