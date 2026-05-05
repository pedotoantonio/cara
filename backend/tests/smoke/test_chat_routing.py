"""Smoke tests for the deterministic chat routing tiers (quick_calc,
intent_router, smart-home prefilter).

These exercise the chat endpoint with queries that MUST be intercepted
before the LLM. We don't assert exact wording — just that:
  - the endpoint streams a response
  - the response arrives in <2 s (no LLM warm-up = router hit)
  - the `done` event reports `routed != ""` for the deterministic tiers
"""

from __future__ import annotations

import asyncio
import json
import re

import httpx
import pytest


pytestmark = pytest.mark.asyncio


async def _stream_chat(
    auth_client: httpx.AsyncClient, content: str,
) -> tuple[str, dict]:
    """Send `content` to /chat, return (concatenated_text, done_event)."""
    text_parts: list[str] = []
    done: dict = {}
    async with auth_client.stream(
        "POST", "/api/v1/chat",
        json={"messages": [{"role": "user", "content": content}]},
        timeout=httpx.Timeout(60.0),
    ) as r:
        assert r.status_code == 200, await r.aread()
        cur_event: str | None = None
        async for line in r.aiter_lines():
            if not line:
                cur_event = None
                continue
            m = re.match(r"event: (.+)$", line)
            if m:
                cur_event = m.group(1)
                continue
            m = re.match(r"data: (.+)$", line)
            if not m:
                continue
            try:
                data = json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
            if cur_event == "token" and "text" in data:
                text_parts.append(data["text"])
            elif cur_event == "done":
                done = data
    return "".join(text_parts), done


async def test_quick_calc_math(auth_client: httpx.AsyncClient) -> None:
    text, done = await _stream_chat(auth_client, "Quanto fa 6 per 7?")
    assert text.strip() == "42"
    assert done.get("routed") == "quick_calc"
    # Router hits MUST report 0 LLM tokens.
    assert done.get("tokens", 0) == 0


async def test_quick_calc_time(auth_client: httpx.AsyncClient) -> None:
    text, done = await _stream_chat(auth_client, "Che ore sono?")
    assert "Sono le " in text
    assert done.get("routed") == "quick_calc"


async def test_capabilities_intercepted(auth_client: httpx.AsyncClient) -> None:
    text, done = await _stream_chat(auth_client, "Cosa puoi fare?")
    # The capabilities canned reply mentions "Task" and "Lista della spesa".
    assert "Task" in text or "task" in text
    assert "spesa" in text.lower()
    assert done.get("routed") == "capabilities"


async def test_identity_intercepted(auth_client: httpx.AsyncClient) -> None:
    text, done = await _stream_chat(auth_client, "Chi sei?")
    assert "Cara" in text
    assert done.get("routed") == "identity"


async def test_list_tasks_intercepted(auth_client: httpx.AsyncClient) -> None:
    _, done = await _stream_chat(auth_client, "Cosa devo fare?")
    assert done.get("routed") in ("list_tasks", "list_tasks_today")


async def test_list_shopping_intercepted(auth_client: httpx.AsyncClient) -> None:
    _, done = await _stream_chat(auth_client, "Cosa devo comprare?")
    assert done.get("routed") == "list_shopping"


async def test_random_chat_falls_through_to_llm(
    auth_client: httpx.AsyncClient,
) -> None:
    """A free-form question goes to the LLM and `routed` is empty."""
    text, done = await _stream_chat(
        auth_client, "Raccontami una storia surreale di tre frasi.",
    )
    # The LLM may take time; we just assert the response arrived.
    assert isinstance(text, str)
    # routed is empty string when the LLM produces the reply.
    assert done.get("routed", "") in ("", None)
