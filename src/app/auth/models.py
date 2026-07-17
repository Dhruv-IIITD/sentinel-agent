"""Authentication domain types, separate from the business Store."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    email: str
    role: str
