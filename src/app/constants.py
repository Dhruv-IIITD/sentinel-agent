"""Shared enums for risk tiers, approval state, and audit actors."""

from __future__ import annotations

from enum import StrEnum


class RiskTier(StrEnum):
    """How an action is gated. See docs/BUILD_PLAN.md §5."""

    READ = "read"  # auto-execute
    REVERSIBLE = "reversible"  # auto-execute + logged
    HIGH_STAKES = "high_stakes"  # always requires approval
    DYNAMIC = "dynamic"  # approval decided at runtime by policy RAG


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"
    EXPIRED = "expired"


class Decision(StrEnum):
    """A human's decision on a pending approval."""

    APPROVE = "approve"
    REJECT = "reject"
    MODIFY = "modify"


class Actor(StrEnum):
    AGENT = "agent"
    HUMAN = "human"
    SYSTEM = "system"


class ThreadStatus(StrEnum):
    ACTIVE = "active"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
