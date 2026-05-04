"""Shared fixtures for CARA E2E smoke tests.

Tests run as black-box HTTP clients against a *running* backend. The default
target is the live container exposed via the nginx-proxy at
`https://192.168.1.23:8455` (TLS self-signed → `verify=False`). Override with
`CARA_TEST_BASE_URL=http://...` for a local dev server.

Each pytest invocation gets a fresh user (`cara-test-<rand>@example.com`) so
runs are independent and parallel-safe. No teardown: old test users sit
quietly in the DB until purged by the next maintenance pass.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest


# Default points at the production-style nginx proxy used by the family.
# Self-signed cert → verify=False. Override per-run via env if you spin up
# a separate dev backend.
DEFAULT_BASE_URL = "https://192.168.1.23:8455"


def _base_url() -> str:
    return os.environ.get("CARA_TEST_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


@pytest.fixture(scope="session")
def base_url() -> str:
    return _base_url()


@pytest.fixture(scope="session")
async def http() -> AsyncIterator[httpx.AsyncClient]:
    """Shared anonymous client for /health and registration."""
    async with httpx.AsyncClient(
        base_url=_base_url(),
        verify=False,
        timeout=httpx.Timeout(10.0, connect=5.0),
    ) as client:
        yield client


@dataclass
class TestUser:
    email: str
    password: str
    full_name: str
    user_id: int
    access_token: str
    refresh_token: str

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


@pytest.fixture(scope="session")
async def test_user(http: httpx.AsyncClient) -> TestUser:
    """Register and log in a fresh user for the whole test session.

    The email is randomised so concurrent runs don't clash and so this fixture
    never depends on the state of a previous run.
    """
    suffix = secrets.token_hex(6)
    email = f"cara-test-{suffix}@example.com"
    password = "test-passw0rd-strong"
    full_name = f"CARA Test {suffix}"

    reg = await http.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert reg.status_code == 201, f"register failed: {reg.status_code} {reg.text}"
    user_data = reg.json()

    login = await http.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed: {login.status_code} {login.text}"
    tokens = login.json()

    return TestUser(
        email=email,
        password=password,
        full_name=full_name,
        user_id=user_data["id"],
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
    )


@pytest.fixture
async def auth_client(test_user: TestUser) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client pre-authenticated as the session test user.

    Function-scoped so each test starts with a clean client, but it shares
    the underlying user/token from the session-scoped fixture.
    """
    async with httpx.AsyncClient(
        base_url=_base_url(),
        verify=False,
        timeout=httpx.Timeout(10.0, connect=5.0),
        headers=test_user.auth_headers,
    ) as client:
        yield client
