"""Shared fixtures for CARA tests.

The smoke suite (`tests/smoke/`) is black-box HTTP against a running
backend. The unit suite (`tests/unit/`) imports modules directly with an
in-memory SQLite session — for that to work, env vars must be set BEFORE
`cara.config` is imported, so the env-var stub lives at module scope here
(this conftest is loaded by pytest before any test module).

Smoke target defaults to `https://192.168.1.23:8455` (self-signed →
`verify=False`). Override with `CARA_TEST_BASE_URL=http://...`.

Each smoke run gets a fresh user (`cara-test-<rand>@example.com`) so runs
are independent and parallel-safe.
"""

from __future__ import annotations

import os

# Stub env so `from cara.config import settings` works under unit tests
# without a real .env. Set BEFORE any cara.* import — must be at module
# scope. Existing values (real .env loaded by pydantic-settings) take
# priority because we use setdefault.
os.environ.setdefault("CARA_ENV", "test")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://cara:cara@localhost:5432/cara_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ROOT_USER", "test")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "test-password-12345")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-for-production-use")

import secrets  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402
from dataclasses import dataclass  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402


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
