"""Small in-memory operator directory for the single-tenant demo.

Passwords are stored only as bcrypt hashes. Durable Postgres users,
registration, and tenant membership are deferred to the multi-tenancy work.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from passlib.context import CryptContext

from .models import User


@dataclass(frozen=True)
class _StoredUser:
    user: User
    password_hash: str


class UserStore:
    def __init__(self, demo_password: str) -> None:
        password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        password_hash = password_context.hash(demo_password)
        self._password_context = password_context
        self._users = {
            email: _StoredUser(User(email=email, role=role), password_hash)
            for email, role in (
                ("operator@demo", "operator"),
                ("supervisor@demo", "supervisor"),
                ("admin@demo", "admin"),
            )
        }

    def get_by_email(self, email: str) -> User | None:
        stored = self._users.get((email or "").strip().lower())
        return stored.user if stored is not None else None

    def verify_password(self, email: str, password: str) -> bool:
        stored = self._users.get((email or "").strip().lower())
        return bool(
            stored is not None
            and self._password_context.verify(password, stored.password_hash)
        )


@lru_cache
def build_user_store(demo_password: str) -> UserStore:
    """Hash the configured demo password once per process."""
    return UserStore(demo_password)
