"""Auth round-trip: register → login → /me → refresh.

Uses the shared `test_user` fixture for the happy path and exercises a few
negative cases inline (wrong password, missing token).
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

import httpx
import pytest

if TYPE_CHECKING:
    from tests.conftest import TestUser


pytestmark = pytest.mark.asyncio


async def test_session_user_can_fetch_me(
    auth_client: httpx.AsyncClient, test_user: TestUser
) -> None:
    r = await auth_client.get("/api/v1/auth/me")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == test_user.user_id
    assert body["email"] == test_user.email
    assert body["full_name"] == test_user.full_name
    assert body["is_active"] is True


async def test_me_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/auth/me")
    assert r.status_code == 401, r.text


async def test_login_wrong_password_rejected(
    http: httpx.AsyncClient, test_user: TestUser
) -> None:
    r = await http.post(
        "/api/v1/auth/login",
        json={"email": test_user.email, "password": "definitely-wrong"},
    )
    assert r.status_code == 401, r.text


async def test_refresh_returns_new_access_token(
    http: httpx.AsyncClient, test_user: TestUser
) -> None:
    r = await http.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": test_user.refresh_token},
    )
    assert r.status_code == 200, r.text
    tokens = r.json()
    assert tokens["access_token"]
    assert tokens["refresh_token"]
    assert tokens["token_type"].lower() == "bearer"


async def test_register_duplicate_email_conflict(
    http: httpx.AsyncClient, test_user: TestUser
) -> None:
    r = await http.post(
        "/api/v1/auth/register",
        json={
            "email": test_user.email,
            "password": "another-passw0rd",
            "full_name": "Duplicate",
        },
    )
    assert r.status_code == 409, r.text


async def test_register_weak_password_rejected(http: httpx.AsyncClient) -> None:
    suffix = secrets.token_hex(4)
    r = await http.post(
        "/api/v1/auth/register",
        json={
            "email": f"weak-{suffix}@example.com",
            "password": "short",  # < 8 chars → schema validation
            "full_name": "Weak",
        },
    )
    assert r.status_code == 422, r.text
