"""FastAPI authentication and RBAC dependencies."""

from __future__ import annotations

from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .models import User
from .tokens import decode_access_token

_bearer = HTTPBearer(auto_error=False)
_SYNTHETIC_ADMIN = User(email="admin@demo", role="admin")


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    settings = request.app.state.settings
    if not settings.auth_enabled:
        return _SYNTHETIC_ADMIN
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="valid bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_access_token(credentials.credentials, settings=settings)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=401,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def require_role(*roles: str) -> Callable:
    async def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(status_code=403, detail="insufficient permissions")
        return current_user

    return dependency
