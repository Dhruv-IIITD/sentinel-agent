"""Validate the ORM models cross-dialect (SQLite stands in for Postgres here).

Confirms `Base.metadata.create_all` succeeds, the JSONB→JSON variant round-trips
a dict, and the UUID default is applied — without needing a live Postgres.
"""

from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.constants import ApprovalStatus, RiskTier
from app.db import models  # noqa: F401  (registers tables)
from app.db.base import Base
from app.db.models import ApprovalRequest, Customer, Order


def test_all_expected_tables_registered():
    names = set(Base.metadata.tables)
    assert {
        "customers",
        "orders",
        "refunds",
        "order_notes",
        "threads",
        "approval_requests",
        "audit_log",
        "tool_executions",
    } <= names


def test_create_all_and_json_roundtrip():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as s:
        c = Customer(name="Alice Rivera", email="alice@example.com")
        s.add(c)
        s.flush()
        s.add(
            Order(
                id=4471,
                customer_id=c.id,
                amount=Decimal("180.00"),
                item_description="Ceramic dinner set",
            )
        )
        ar = ApprovalRequest(
            thread_id="th-1",
            tool_name="issue_refund",
            tool_args={"order_id": 4471, "amount": 180.0},
            risk_tier=RiskTier.DYNAMIC,
            status=ApprovalStatus.PENDING,
            policy_citation="Refunds > $50 require manager approval.",
        )
        s.add(ar)
        s.commit()

        got = s.scalar(select(ApprovalRequest).where(ApprovalRequest.thread_id == "th-1"))
        assert got is not None
        assert got.tool_args["order_id"] == 4471  # JSON round-trip
        assert got.status == ApprovalStatus.PENDING
        assert got.id is not None  # uuid default applied
