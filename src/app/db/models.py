"""ORM models — business tables + HITL/audit tables.

Grouped in one module so Alembic autogenerate and `Base.metadata.create_all`
see every table. The LangGraph checkpointer manages its own tables
(`checkpoints`, `checkpoint_writes`, ...) separately via `AsyncPostgresSaver`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..constants import ApprovalStatus, RiskTier
from .base import JSONB_, Base, TimestampMixin

# ---------------------------------------------------------------------------
# Business domain (e-commerce customer-support ops)
# ---------------------------------------------------------------------------


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)

    orders: Mapped[list["Order"]] = relationship(back_populates="customer")


class Product(TimestampMixin, Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    emoji: Mapped[str] = mapped_column(String(32), nullable=False, default="")


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="delivered")
    item_description: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    shipping_address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payment_ref: Mapped[str | None] = mapped_column(String(255))
    delivered_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    customer: Mapped["Customer"] = relationship(back_populates="orders")
    refunds: Mapped[list["Refund"]] = relationship(back_populates="order")
    notes: Mapped[list["OrderNote"]] = relationship(back_populates="order")


class Refund(TimestampMixin, Base):
    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="issued")
    reason: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    provider: Mapped[str | None] = mapped_column(String(40))
    provider_refund_id: Mapped[str | None] = mapped_column(String(255))
    # Ties a refund row back to the exactly-once execution that created it.
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)

    order: Mapped["Order"] = relationship(back_populates="refunds")


class OrderNote(TimestampMixin, Base):
    __tablename__ = "order_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    author: Mapped[str] = mapped_column(String(120), nullable=False, default="agent")
    note: Mapped[str] = mapped_column(Text, nullable=False)

    order: Mapped["Order"] = relationship(back_populates="notes")


# ---------------------------------------------------------------------------
# HITL / audit
# ---------------------------------------------------------------------------


class Thread(TimestampMixin, Base):
    """One conversation. `thread_id` mirrors the LangGraph checkpointer thread."""

    __tablename__ = "threads"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(120), nullable=False, default="anonymous")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    title: Mapped[str | None] = mapped_column(String(300))
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class ApprovalRequest(TimestampMixin, Base):
    """A pending (or decided) approval — what the dashboard reads."""

    __tablename__ = "approval_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    checkpoint_id: Mapped[str | None] = mapped_column(String(128))
    # The LLM tool_call id this approval gates — the resume anchor.
    tool_call_id: Mapped[str | None] = mapped_column(String(128), index=True)

    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    tool_args: Mapped[dict] = mapped_column(JSONB_, nullable=False, default=dict)
    risk_tier: Mapped[str] = mapped_column(String(20), nullable=False, default=RiskTier.HIGH_STAKES)
    policy_citation: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ApprovalStatus.PENDING, index=True
    )
    modified_args: Mapped[dict | None] = mapped_column(JSONB_)
    reason: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(String(120))
    decided_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    escalated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class AuditLog(TimestampMixin, Base):
    """Append-only record of every action and decision."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    actor: Mapped[str] = mapped_column(String(20), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(120))
    args: Mapped[dict | None] = mapped_column(JSONB_)
    result: Mapped[dict | None] = mapped_column(JSONB_)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), index=True)
    policy_ref: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    tokens: Mapped[int | None] = mapped_column(Integer)
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ToolExecution(TimestampMixin, Base):
    """Idempotency ledger — a unique key guarantees exactly-once side effects.

    A resumed graph re-runs the approval node; this table makes the *effect*
    fire at most once regardless of how many times the node re-executes.
    """

    __tablename__ = "tool_executions"

    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    args_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB_)
    compensated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
