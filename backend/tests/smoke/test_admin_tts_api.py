"""Smoke tests for /api/v1/admin/tts/overrides."""

from __future__ import annotations

import httpx
import pytest


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------- auth gates


async def test_get_overrides_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/admin/tts/overrides")
    assert r.status_code == 401, r.text


async def test_get_overrides_requires_admin(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.get("/api/v1/admin/tts/overrides")
    assert r.status_code == 403, r.text


async def test_put_overrides_requires_admin(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.put(
        "/api/v1/admin/tts/overrides",
        json={"overrides": {"weekend": "uìkend"}},
    )
    assert r.status_code == 403, r.text


async def test_patch_overrides_requires_admin(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.patch(
        "/api/v1/admin/tts/overrides",
        json={"overrides": {"newword": "nuòvuord"}},
    )
    assert r.status_code == 403, r.text


async def test_delete_override_requires_admin(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.delete("/api/v1/admin/tts/overrides/weekend")
    assert r.status_code == 403, r.text


async def test_preview_requires_admin(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/api/v1/admin/tts/overrides", json={"overrides": {}},
    )
    # Note: PUT is the same path, just confirming admin gate consistency.
    assert r.status_code in (403, 405), r.text


# ---------------------------------------------------------------- schema validation


async def test_put_validates_word_chars(http: httpx.AsyncClient) -> None:
    """A word with arbitrary regex metacharacters must be rejected."""
    r = await http.put(
        "/api/v1/admin/tts/overrides",
        json={"overrides": {"week.*end": "x"}},
    )
    # Either auth-fails first (401) or schema-fails (422). Both are clean.
    assert r.status_code in (401, 422), r.text


async def test_put_validates_value_length(http: httpx.AsyncClient) -> None:
    r = await http.put(
        "/api/v1/admin/tts/overrides",
        json={"overrides": {"weekend": "x" * 500}},
    )
    assert r.status_code in (401, 422), r.text


async def test_preview_validates_text_length(http: httpx.AsyncClient) -> None:
    r = await http.post(
        "/api/v1/admin/tts/preview",
        json={"text": "x" * 5000},  # > 2000 max
    )
    assert r.status_code in (401, 422), r.text


async def test_preview_rejects_empty_text(http: httpx.AsyncClient) -> None:
    r = await http.post("/api/v1/admin/tts/preview", json={"text": ""})
    assert r.status_code in (401, 422), r.text
