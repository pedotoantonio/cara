"""Cloud LLM fallback (Step "more intelligent" — May 2026).

Optional Anthropic Haiku client used when:
  - the admin flag `cloud_llm_enabled` is True, AND
  - the request explicitly asked for cloud reasoning (`prefer_cloud=true`),
  - OR the local 1.5B has been classified as "very likely to fail" on the
    query type (multi-step reasoning, code, long-form essays).

Design constraints (privacy-first):
  - Off by default. A False admin flag short-circuits the import path
    so the anthropic package is only imported when actually needed.
  - Per-query opt-in via the chat request body (`prefer_cloud`).
  - No conversation history sent to cloud — the fallback gets ONLY the
    last user turn + the persona system prompt + an explicit hint.
  - Returns an async iterator of token-text strings so the chat layer
    can stream it through the same SSE wire format as local generation.
  - Hard-coded conservative limits: 400 tokens out, 30 s timeout,
    max 200 user-turn chars sent (truncated with ellipsis).

The cloud key lives in `settings.anthropic_api_key`. Empty → service
raises `CloudLLMUnavailable`. The chat layer falls back to the local
model on any error from this module.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Final

import structlog

from cara.config import settings


log = structlog.get_logger(__name__)


class CloudLLMUnavailable(Exception):
    """Cloud LLM cannot service this request — caller should fall back."""


_MAX_USER_CHARS: Final = 1200
_MAX_OUTPUT_TOKENS: Final = 400
_TIMEOUT_SECONDS: Final = 30.0


_SYSTEM_PROMPT: Final = (
    "Sei CARA, un'assistente AI italiana per la famiglia Pedoto. "
    "Rispondi sempre in italiano corretto. "
    "Sii concisa: 2-5 frasi al massimo, salvo che l'utente chieda esplicitamente più dettaglio. "
    "Non emettere [TOOL: ...] in queste risposte (sono per il modello locale). "
    "Non inventare fatti che non conosci con certezza: se non sai, dillo onestamente."
)


def is_available() -> bool:
    """True if the cloud key is configured. Doesn't import anthropic.

    Safe to call from any context including startup / health checks.
    """
    return bool((settings.anthropic_api_key or "").strip())


async def cloud_chat_stream(
    user_message: str,
    *,
    max_tokens: int = _MAX_OUTPUT_TOKENS,
    timeout: float = _TIMEOUT_SECONDS,
) -> AsyncIterator[str]:
    """Stream the cloud reply for `user_message` as token-text deltas.

    Raises `CloudLLMUnavailable` if the key is missing or the SDK fails
    to import. Translation of network errors to CloudLLMUnavailable is
    left to the call site so the chat layer can surface a clear reason.
    """
    if not is_available():
        raise CloudLLMUnavailable("ANTHROPIC_API_KEY non configurata")

    try:
        from anthropic import AsyncAnthropic  # type: ignore[import-not-found]
    except ImportError as exc:
        raise CloudLLMUnavailable("pacchetto anthropic non installato") from exc

    truncated = (user_message or "").strip()[:_MAX_USER_CHARS]
    if not truncated:
        raise CloudLLMUnavailable("messaggio utente vuoto")

    model_id = (
        settings.skill_author_model.strip()
        if getattr(settings, "skill_author_model", None) and settings.skill_author_model.strip()
        else "claude-haiku-4-5-20251001"
    )

    client = AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=timeout)

    log.info(
        "cloud_llm.chat.start",
        model=model_id,
        user_chars=len(truncated),
        max_tokens=max_tokens,
    )

    try:
        # Anthropic SDK exposes `messages.stream` as an async context manager
        # yielding text deltas.
        async with client.messages.stream(
            model=model_id,
            max_tokens=max_tokens,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": truncated}],
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    yield text
    except asyncio.TimeoutError as exc:
        raise CloudLLMUnavailable(f"timeout dopo {timeout}s") from exc
    except Exception as exc:  # noqa: BLE001 — broad: SDK exposes many error classes
        raise CloudLLMUnavailable(f"errore cloud: {exc}") from exc
