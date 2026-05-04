"""Liveness checks: the backend must answer and the LLM must be loaded.

These are the cheapest tests in the suite. If they fail, every other test
will fail too — so they run first and short-circuit the rest.
"""

from __future__ import annotations

import httpx
import pytest


pytestmark = pytest.mark.asyncio


async def test_root_health(http: httpx.AsyncClient) -> None:
    r = await http.get("/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "env" in body


async def test_chat_health_reports_model(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/chat/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    # The path won't change often, but if it does we want a loud test failure
    # rather than a silent regression where the LLM didn't load.
    assert "model_path" in body and body["model_path"], "LLM model path missing"
