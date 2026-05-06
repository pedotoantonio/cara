"""Smoke tests for the first-run setup wizard API.

Most tests run against the live backend which already has an admin
configured (Antonio). Specifically, the Step-1 admin creation cannot
be exercised live without dropping the user, so it's covered with
auth-gate smokes (refused when admin exists) and unit tests.
"""

from __future__ import annotations

import pytest

API = "/api/v1/setup"


@pytest.mark.asyncio
async def test_setup_status_anonymous(http) -> None:
    r = await http.get(f"{API}/status")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 1
    assert body["has_admin"] is True
    assert "steps" in body
    assert len(body["steps"]) == 8


@pytest.mark.asyncio
async def test_setup_admin_refused_when_admin_exists(http) -> None:
    """The anon admin-create endpoint refuses if an admin already
    exists — this is the canonical safety gate."""
    r = await http.post(
        f"{API}/admin",
        json={
            "email": "should-fail@example.com",
            "password": "test-passw0rd-strong-1",
            "full_name": "Should Fail",
        },
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_setup_endpoints_require_auth(http) -> None:
    """Every endpoint past Step 1 requires an admin JWT."""
    for path, method, body in [
        ("/cert/regenerate", "post", {}),
        ("/cert/skip", "post", {}),
        ("/family", "post", {"family_name": "X", "glossary": [], "family_size": 4, "language": "it"}),
        ("/voice", "post", {}),
        ("/llm", "post", {"quality_mode": "fast", "tone_preset": "default", "max_new_tokens": 512, "validation_enabled": False, "cognitive_mode": False}),
        ("/homeassistant/test", "post", {"url": "http://localhost", "token": "x"}),
        ("/homeassistant", "post", {"enabled": False, "url": "http://localhost"}),
        ("/vapid/generate", "post", {}),
        ("/telegram", "post", {"enabled": False, "allowed_chat_ids": []}),
        ("/integrations/complete", "post", {}),
        ("/google", "post", {}),
        ("/cloud", "post", {"enabled": False}),
        ("/cloud/test", "post", {"api_key": "x"}),
        ("/feature-flags", "post", {
            "internet_enabled": False, "news_enabled": False, "radio_enabled": False,
            "cda_enabled": True, "cda_safe_search_for_minors": True,
            "proactive_suggestions_enabled": False, "habit_learning_enabled": False,
            "skill_dispatcher_tier2_enabled": True,
            "skill_dispatcher_tier3_enabled": False,
            "voice_recognition_enabled": True,
        }),
        ("/complete", "post", {}),
        ("/reset", "post", {}),
    ]:
        if method == "post":
            r = await http.post(f"{API}{path}", json=body)
        else:
            r = await http.get(f"{API}{path}")
        assert r.status_code in (401, 403), f"{path} expected 401/403, got {r.status_code}"


@pytest.mark.asyncio
async def test_homeassistant_test_with_admin(admin_client) -> None:
    """admin_client gets through auth, then probe fails with 502 since
    the URL is bogus — but the failure is structured, not 500."""
    if admin_client is None:
        pytest.skip("admin_client fixture not available")
    r = await admin_client.post(
        f"{API}/homeassistant/test",
        json={"url": "http://does-not-resolve.invalid", "token": "x"},
    )
    assert r.status_code == 502


@pytest.mark.asyncio
async def test_cloud_test_rejects_empty_key(admin_client) -> None:
    if admin_client is None:
        pytest.skip("admin_client fixture not available")
    r = await admin_client.post(f"{API}/cloud/test", json={"api_key": ""})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_save_family_persists(admin_client) -> None:
    if admin_client is None:
        pytest.skip("admin_client fixture not available")
    r = await admin_client.post(
        f"{API}/family",
        json={
            "family_name": "Famiglia Smoke",
            "glossary": ["Antonio", "Sara"],
            "family_size": 3,
            "language": "it",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["family_name"] == "Famiglia Smoke"
    assert "Antonio" in body["family_glossary"]


@pytest.mark.asyncio
async def test_feature_flags_save_round_trip(admin_client) -> None:
    if admin_client is None:
        pytest.skip("admin_client fixture not available")
    payload = {
        "internet_enabled": False,
        "news_enabled": False,
        "radio_enabled": False,
        "cda_enabled": True,
        "cda_safe_search_for_minors": True,
        "proactive_suggestions_enabled": False,
        "habit_learning_enabled": False,
        "skill_dispatcher_tier2_enabled": True,
        "skill_dispatcher_tier3_enabled": False,
        "voice_recognition_enabled": True,
    }
    r = await admin_client.post(f"{API}/feature-flags", json=payload)
    assert r.status_code == 200
    assert r.json() == payload


@pytest.mark.asyncio
async def test_status_reports_progress_after_save(admin_client, http) -> None:
    """After saving family, completed_steps grows."""
    if admin_client is None:
        pytest.skip("admin_client fixture not available")
    await admin_client.post(
        f"{API}/family",
        json={"family_name": "Prog", "glossary": [], "family_size": 2, "language": "it"},
    )
    r = await http.get(f"{API}/status")
    assert r.status_code == 200
    assert "family" in r.json()["completed_steps"]
