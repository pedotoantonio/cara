"""Smoke tests for /api/v1/face/*. Hits a live backend.

The face router is admin-only, so the bulk of these tests use the
`admin_client` fixture and skip gracefully when no admin is configured.
A handful run against the regular `http` / `auth_client` fixtures to
prove the auth gate.

Round-trips every Phase 1+2 endpoint:

  POST     /face/profiles
  GET      /face/profiles
  GET      /face/profiles/{id}
  PATCH    /face/profiles/{id}
  DELETE   /face/profiles/{id}
  POST     /face/profiles/{id}/descriptors
  GET      /face/profiles/{id}/descriptors
  POST     /face/match
  GET/PUT  /face/settings
"""

from __future__ import annotations

import random
import secrets

import httpx
import pytest


pytestmark = pytest.mark.asyncio


def _random_descriptor(seed: int | None = None) -> list[float]:
    rng = random.Random(seed)
    # Gaussian around 0 with sd 0.1 — matches face-api.js descriptor scale
    # in absolute value range (descriptors are L2-normalised after the
    # recognition net, but the tests don't care about normalisation).
    return [rng.gauss(0.0, 0.1) for _ in range(128)]


# ─── Auth gate ─────────────────────────────────────────────────────────


async def test_anonymous_blocked(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/face/profiles")
    assert r.status_code == 401, r.text


async def test_non_admin_blocked(auth_client: httpx.AsyncClient) -> None:
    """Regular users (no is_admin) must NOT be able to list profiles —
    face data is admin-managed."""
    r = await auth_client.get("/api/v1/face/profiles")
    assert r.status_code in (401, 403), r.text


# ─── Profile CRUD round-trip ───────────────────────────────────────────


async def test_profile_crud_full_roundtrip(
    admin_client: httpx.AsyncClient | None,
) -> None:
    if admin_client is None:
        pytest.skip("no admin configured in test env")

    name = f"FaceTest-{secrets.token_hex(4)}"

    # Create
    r = await admin_client.post(
        "/api/v1/face/profiles",
        json={
            "display_name": name,
            "is_child": False,
            "match_threshold": 0.5,
            "consent_text_version": "v1.0",
        },
    )
    assert r.status_code == 201, r.text
    created = r.json()
    pid = created["id"]
    assert created["display_name"] == name
    assert created["descriptor_count"] == 0
    assert created["active"] is True

    try:
        # 409 on duplicate active name
        r = await admin_client.post(
            "/api/v1/face/profiles",
            json={
                "display_name": name,
                "consent_text_version": "v1.0",
            },
        )
        assert r.status_code == 409, r.text

        # List includes the new profile
        r = await admin_client.get("/api/v1/face/profiles")
        assert r.status_code == 200, r.text
        names = [p["display_name"] for p in r.json()]
        assert name in names

        # Get single
        r = await admin_client.get(f"/api/v1/face/profiles/{pid}")
        assert r.status_code == 200, r.text
        assert r.json()["id"] == pid

        # Patch — rename + flip child + tune threshold
        new_name = f"{name}-renamed"
        r = await admin_client.patch(
            f"/api/v1/face/profiles/{pid}",
            json={
                "display_name": new_name,
                "is_child": True,
                "match_threshold": 0.55,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["display_name"] == new_name
        assert body["is_child"] is True
        assert body["match_threshold"] == pytest.approx(0.55)
    finally:
        # Delete (cascades descriptors)
        r = await admin_client.delete(f"/api/v1/face/profiles/{pid}")
        assert r.status_code == 204, r.text

    # 404 on second delete
    r = await admin_client.delete(f"/api/v1/face/profiles/{pid}")
    assert r.status_code == 404, r.text


# ─── Descriptor add + list + server-match ──────────────────────────────


async def test_descriptors_and_server_match(
    admin_client: httpx.AsyncClient | None,
) -> None:
    if admin_client is None:
        pytest.skip("no admin configured in test env")

    name = f"FaceTest-{secrets.token_hex(4)}"
    r = await admin_client.post(
        "/api/v1/face/profiles",
        json={"display_name": name, "consent_text_version": "v1.0"},
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    try:
        # Bulk add: 2 enrollment + 1 continuous
        d_enrollment = _random_descriptor(seed=42)
        items = [
            {"descriptor": d_enrollment, "source": "enrollment", "quality": 0.9},
            {
                "descriptor": _random_descriptor(seed=43),
                "source": "enrollment",
                "quality": 0.88,
            },
            {
                "descriptor": _random_descriptor(seed=44),
                "source": "continuous",
                "quality": 0.81,
            },
        ]
        r = await admin_client.post(
            f"/api/v1/face/profiles/{pid}/descriptors",
            json={"items": items},
        )
        assert r.status_code == 201, r.text
        rows = r.json()
        assert len(rows) == 3
        assert all(len(row["descriptor"]) == 128 for row in rows)
        sources = sorted(row["source"] for row in rows)
        assert sources == ["continuous", "enrollment", "enrollment"]

        # List
        r = await admin_client.get(f"/api/v1/face/profiles/{pid}/descriptors")
        assert r.status_code == 200, r.text
        assert len(r.json()) == 3

        # Profile reports the right count
        r = await admin_client.get(f"/api/v1/face/profiles/{pid}")
        assert r.status_code == 200
        assert r.json()["descriptor_count"] == 3

        # Server-side match should find the profile we just enrolled when
        # we send the exact descriptor we used at enrollment.
        r = await admin_client.post(
            "/api/v1/face/match", json={"descriptor": d_enrollment}
        )
        assert r.status_code == 200, r.text
        match = r.json()["match"]
        assert match is not None
        assert match["profile_id"] == pid
        assert match["distance"] < 0.5
    finally:
        await admin_client.delete(f"/api/v1/face/profiles/{pid}")


async def test_descriptor_validation_rejects_wrong_dim(
    admin_client: httpx.AsyncClient | None,
) -> None:
    if admin_client is None:
        pytest.skip("no admin configured in test env")

    name = f"FaceTest-{secrets.token_hex(4)}"
    r = await admin_client.post(
        "/api/v1/face/profiles",
        json={"display_name": name, "consent_text_version": "v1.0"},
    )
    assert r.status_code == 201
    pid = r.json()["id"]
    try:
        # 127 dims — Pydantic must reject.
        bad = [0.1] * 127
        r = await admin_client.post(
            f"/api/v1/face/profiles/{pid}/descriptors",
            json={"items": [{"descriptor": bad, "source": "enrollment"}]},
        )
        assert r.status_code == 422, r.text

        # Wrong source enum.
        r = await admin_client.post(
            f"/api/v1/face/profiles/{pid}/descriptors",
            json={
                "items": [
                    {
                        "descriptor": _random_descriptor(seed=1),
                        "source": "magic",
                    }
                ]
            },
        )
        assert r.status_code == 422, r.text
    finally:
        await admin_client.delete(f"/api/v1/face/profiles/{pid}")


# ─── Settings round-trip ───────────────────────────────────────────────


async def test_settings_roundtrip(
    admin_client: httpx.AsyncClient | None,
) -> None:
    if admin_client is None:
        pytest.skip("no admin configured in test env")

    r = await admin_client.get("/api/v1/face/settings")
    assert r.status_code == 200, r.text
    before = r.json()
    assert isinstance(before["enabled"], bool)
    assert isinstance(before["default_threshold"], float)

    # Flip the toggle and put it back.
    r = await admin_client.put(
        "/api/v1/face/settings", json={"enabled": not before["enabled"]}
    )
    assert r.status_code == 200, r.text
    flipped = r.json()
    assert flipped["enabled"] != before["enabled"]

    r = await admin_client.put(
        "/api/v1/face/settings", json={"enabled": before["enabled"]}
    )
    assert r.status_code == 200, r.text
    restored = r.json()
    assert restored["enabled"] == before["enabled"]


async def test_server_match_empty_db_returns_none(
    admin_client: httpx.AsyncClient | None,
) -> None:
    """Calling /face/match with no profiles + no descriptors must return
    `{"match": null}` rather than 500."""
    if admin_client is None:
        pytest.skip("no admin configured in test env")

    # We can't guarantee an empty DB, so we just assert the contract:
    # the endpoint never 5xxs and always returns the same shape.
    r = await admin_client.post(
        "/api/v1/face/match",
        json={"descriptor": _random_descriptor(seed=999)},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "match" in body
    assert body["match"] is None or "profile_id" in body["match"]
