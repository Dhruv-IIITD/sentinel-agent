"""Operator login and identity endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..auth.deps import get_current_user
from ..auth.models import User
from ..auth.tokens import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
async def login(body: LoginRequest, request: Request) -> dict:
    users = request.app.state.users
    user = users.get_by_email(body.email)
    if user is None or not users.verify_password(body.email, body.password):
        raise HTTPException(
            status_code=401,
            detail="invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {
        "access_token": create_access_token(user, settings=request.app.state.settings),
        "token_type": "bearer",
        "role": user.role,
    }


@router.get("/me")
async def me(request: Request, current_user: User = Depends(get_current_user)) -> dict:
    return {
        "email": current_user.email,
        "role": current_user.role,
        "operator_approval_limit": request.app.state.settings.operator_approval_limit,
    }
