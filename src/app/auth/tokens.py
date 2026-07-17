"""HS256 access-token creation and verification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from ..config import settings as default_settings
from .models import User

ALGORITHM = "HS256"


def create_access_token(user: User, settings=default_settings) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.email,
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str, settings=default_settings) -> User:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    email = payload.get("sub")
    role = payload.get("role")
    if not isinstance(email, str) or not email or not isinstance(role, str) or not role:
        raise jwt.InvalidTokenError("token is missing subject or role")
    return User(email=email, role=role)
