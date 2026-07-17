"""Operator JWT authentication, RBAC, and approval limits."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth.deps import require_role
from app.auth.models import User
from app.auth.tokens import create_access_token
from app.auth.users import build_user_store
from app.config import Settings
from app.domain.ecommerce import MemoryStore
from app.main import app

DEMO_PASSWORD = "demo-password"
JWT_SECRET = "auth-test-secret-at-least-32-bytes"


def _settings(auth_enabled: bool = True) -> Settings:
    return Settings(
        auth_enabled=auth_enabled,
        jwt_secret=JWT_SECRET,
        demo_user_password=DEMO_PASSWORD,
        operator_approval_limit=100.0,
        database_url="",
        checkpoint_backend="memory",
    )


@contextmanager
def _auth_client() -> Iterator[TestClient]:
    with TestClient(app) as client:
        auth_settings = _settings()
        app.state.settings = auth_settings
        app.state.users = build_user_store(DEMO_PASSWORD)
        app.state.store = MemoryStore()
        yield client


def _login(client: TestClient, email: str) -> str:
    response = client.post(
        "/auth/login",
        json={"email": email, "password": DEMO_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_build_user_store_is_cached_per_demo_password():
    assert build_user_store(DEMO_PASSWORD) is build_user_store(DEMO_PASSWORD)


def test_login_accepts_correct_credentials_and_rejects_bad_credentials():
    with _auth_client() as client:
        response = client.post(
            "/auth/login",
            json={"email": "operator@demo", "password": DEMO_PASSWORD},
        )
        assert response.status_code == 200
        assert response.json()["token_type"] == "bearer"
        assert response.json()["role"] == "operator"

        wrong = client.post(
            "/auth/login",
            json={"email": "operator@demo", "password": "wrong"},
        )
        missing = client.post(
            "/auth/login",
            json={"email": "unknown@demo", "password": DEMO_PASSWORD},
        )
        assert wrong.status_code == 401
        assert missing.status_code == 401


def test_me_requires_valid_token_when_auth_is_enabled():
    with _auth_client() as client:
        token = _login(client, "supervisor@demo")
        valid = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert valid.status_code == 200
        assert valid.json() == {
            "email": "supervisor@demo",
            "role": "supervisor",
            "operator_approval_limit": 100.0,
        }

        assert client.get("/auth/me").status_code == 401
        assert client.get(
            "/auth/me", headers={"Authorization": "Bearer not-a-token"}
        ).status_code == 401


def test_enabled_auth_protects_operator_routes_but_leaves_store_open():
    with _auth_client() as client:
        assert client.get("/audit").status_code == 401
        assert client.get("/store/products").status_code == 200
        assert client.get("/healthz").status_code == 200

        token = _login(client, "operator@demo")
        assert client.get(
            "/audit", headers={"Authorization": f"Bearer {token}"}
        ).status_code == 200


def test_require_role_rejects_operator_and_allows_admin():
    role_app = FastAPI()
    role_app.state.settings = _settings()

    @role_app.get("/admin")
    async def admin_only(user: User = Depends(require_role("admin"))) -> dict:
        return {"email": user.email}

    operator_token = create_access_token(User("operator@demo", "operator"), _settings())
    admin_token = create_access_token(User("admin@demo", "admin"), _settings())
    with TestClient(role_app) as client:
        denied = client.get(
            "/admin", headers={"Authorization": f"Bearer {operator_token}"}
        )
        allowed = client.get(
            "/admin", headers={"Authorization": f"Bearer {admin_token}"}
        )
    assert denied.status_code == 403
    assert allowed.status_code == 200


def test_operator_limit_blocks_before_graph_is_touched():
    with _auth_client() as client:
        store = app.state.store
        approval = asyncio.run(store.create_approvals(
            "auth-limit",
            "checkpoint-1",
            [{
                "tool_call_id": "refund-limit",
                "tool": "issue_refund",
                "args": {"order_id": 4471, "amount": 180.0},
            }],
        ))[0]
        app.state.graph = None  # any graph access after the limit check would fail the request
        token = _login(client, "operator@demo")

        response = client.post(
            f"/approvals/{approval['id']}/decision",
            json={"decision": "approve"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "this action exceeds your approval limit; a supervisor is required"
        }
        assert store.approvals[approval["id"]]["status"] == "pending"


def test_auth_disabled_preserves_token_free_operator_endpoints():
    with TestClient(app) as client:
        app.state.store = MemoryStore()
        response = client.get("/audit")
        assert response.status_code == 200
        assert client.get("/auth/me").json() == {
            "email": "admin@demo",
            "role": "admin",
            "operator_approval_limit": 100.0,
        }
