"""Web-search fallback stage for the chat pipeline.

The 1.5B Qwen running on the NPU has a 2024 knowledge cutoff and no
direct internet access, so questions about *now* — "cosa c'è da fare a
Ferrara stasera?", "ultime notizie su X", "che tempo fa fra un'ora?" —
trip a long disclaimer ("come assistente virtuale non ho informazioni
in tempo reale…") that's worse than useless.

This stage sits AFTER `intent_router` in the pipeline. When the user's
message looks like a real-time query, we:

1. Run a web search via `cda.search.chain.build_default_chain()` —
   SearXNG when configured, DDG fallback. Both already exist for the
   Content Discovery Agent so no new infrastructure is needed.
2. Build a grounded prompt: the top hits' title/domain/snippet, plus
   strict anti-disclaimer instructions, plus today's date so "oggi"
   in the user's question gets resolved correctly.
3. Stream the LLM through the standard SSE shape so the chat UI sees
   it as a normal model reply.

If web search yields zero hits, we Miss and let the chat fall through
to the plain LLM (which will likely disclaim, but at least we tried).

Toggle: admin setting `chat_web_fallback_enabled` (default True).
"""

from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import structlog
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cara.ai import get_llm_service
from cara.ai.llm import LLMUnavailableError
from cara.api.v1._chat_sse import sse_frame as _sse
from cara.cda.base import SearchHit
from cara.cda.search.chain import build_default_chain
from cara.models.user import User
from cara.services import admin_settings as admin_svc


log = structlog.get_logger(__name__)


# ─── Heuristic: does this query need fresh information? ─────────────
#
# We err on the side of triggering more often — the LLM falling back
# to web grounding is rarely worse than a generic refusal, while
# missing a real-time question is silently bad UX. Tuning these is
# cheap (regex), so we widen them as we encounter false-negative
# user reports.

_REALTIME_PATTERNS = [
    # Time references
    r"\boggi\b",
    r"\bstasera\b",
    r"\bstamattin[ae]\b",
    r"\bstanotte\b",
    r"\bdomani\b",
    r"\bquesta\s+settimana\b",
    r"\bquesto\s+(?:weekend|fine\s*settimana)\b",
    r"\bin\s+tempo\s+reale\b",
    r"\badesso\b",
    r"\bproprio\s+ora\b",
    r"\bin\s+questo\s+momento\b",
    # Things that change frequently
    r"\bevent[oi]\b",
    r"\bmanifestazion[ei]\b",
    r"\bconcert[oi]\b",
    r"\bsagre?\b",
    r"\bfier[ae]\b",
    r"\bcosa\s+(?:c'è|fare|ce\s+sta)\b",
    r"\bche\s+c'è\b",
    r"\bche\s+(?:fare|si\s+fa)\b",
    r"\bda\s+fare\b",
    # News / current events
    r"\b(?:ultim[ie]|ultime)\s+notizi[ae]\b",
    r"\bnotizi[ae]\s+(?:di|su|sul|sull[ao'])\b",
    r"\baggiornamento\s+(?:su|sul|sulla)\b",
    r"\bcom'?è\s+andata\s+(?:la|il|lo)\b",
    # Open-ended "what is" about specific entities (likely needs web)
    r"\bchi\s+(?:è|ha\s+vinto|sta\s+vincendo)\b",
    r"\bquant[oei]\s+costa\b",
    r"\bdov'?è\b",
    r"\bquand'?è\b",
]
_REALTIME_RE = re.compile("|".join(_REALTIME_PATTERNS), re.IGNORECASE)


# Domain labels for politer grounding sentences. The LLM tends to copy
# the domain verbatim if we don't normalise — "ansa.it" reads better
# than "https://www.ansa.it".

def _short_domain(url: str) -> str:
    if not url:
        return ""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:  # noqa: BLE001
        return url[:32]


# ─── Prompt assembly ────────────────────────────────────────────────


def _grounding_prompt(query: str, hits: list[SearchHit]) -> str:
    """Build the LLM prompt that turns search hits into a synthesised
    Italian answer. Strict anti-disclaimer wording — the 1.5B obeys
    direct negative imperatives more reliably than soft suggestions."""

    today_iso = date.today().isoformat()

    # Truncate snippets aggressively — the 1.5B context is small and
    # 3 short snippets give better synthesis than 10 noisy ones.
    snippet_lines: list[str] = []
    for i, h in enumerate(hits[:5], start=1):
        title = (h.title or "").strip()[:120]
        snippet = (h.snippet or "").strip().replace("\n", " ")[:240]
        domain = _short_domain(h.url or "")
        snippet_lines.append(f"{i}. {title} · {domain} · {snippet}")
    sources = "\n".join(snippet_lines) if snippet_lines else "(nessun risultato)"

    system = (
        "Sei CARA, l'assistente di casa della famiglia Pedoto. "
        "Rispondi in italiano, in 2-4 frasi semplici, riportando solo "
        "informazioni presenti nei risultati di ricerca qui sotto. "
        "Vietato dire 'come assistente virtuale', 'non ho informazioni "
        "in tempo reale' o frasi simili: i risultati sono già recenti. "
        "Se i risultati sono incerti, dillo brevemente ('non ho trovato "
        "una conferma chiara'); non inventare date né luoghi assenti "
        "dai risultati. Cita una fonte come 'secondo <sito>' quando ha "
        "senso."
    )
    user_block = (
        f"Data di oggi: {today_iso}\n"
        f"Domanda dell'utente: {query.strip()}\n\n"
        f"Risultati di ricerca recenti:\n{sources}\n\n"
        "Rispondi ora."
    )

    # Qwen2.5 chat template — same shape used by `_chat_prompt.py`.
    return (
        "<|im_start|>system\n"
        f"{system}<|im_end|>\n"
        "<|im_start|>user\n"
        f"{user_block}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


# ─── Stage entry point ──────────────────────────────────────────────


async def try_web_search(
    *,
    session: AsyncSession,
    user: User,
    last_user_q: str | None,
    attached_files: list,
    convo: Any,
) -> StreamingResponse | None:
    """Try to answer the user's question with web-grounded LLM output.

    Miss conditions (return None, let the next stage / plain LLM handle):
      - feature disabled by admin
      - empty query, or query with attached files (LLM already has
        better grounding from those files)
      - heuristic doesn't match → not a realtime question
      - search returns zero hits → nothing to ground on
    """
    if not last_user_q or attached_files:
        return None

    enabled = await admin_svc.get(session, "chat_web_fallback_enabled")
    if enabled is False:
        return None

    if not _REALTIME_RE.search(last_user_q):
        return None

    log.info("chat.web_fallback.triggered", q=last_user_q[:120])

    # Run the search. Both providers raise on hard failure; we treat
    # any exception or empty result as a miss so the LLM still gets a
    # chance.
    chain = build_default_chain()
    try:
        hits: list[SearchHit] = await chain.search(last_user_q, limit=5)
    except Exception as exc:  # noqa: BLE001
        log.warning("chat.web_fallback.search_failed", error=str(exc))
        return None

    if not hits:
        log.info("chat.web_fallback.no_hits")
        return None

    prompt = _grounding_prompt(last_user_q, hits)
    convo_id_str = str(getattr(convo, "id", "")) if convo else ""

    # Sources block we attach at the end of the assistant answer so
    # the user can click through. Kept short — full URL goes in tags
    # the frontend may render as link badges.
    sources_block = "\n\n— Fonti: " + ", ".join(
        f"{_short_domain(h.url)}" for h in hits[:3] if h.url
    )

    async def _stream() -> AsyncIterator[bytes]:
        yield _sse("meta", {
            "conversation_id": convo_id_str,
            "routed": "web_search",
        })
        try:
            llm = get_llm_service()
        except LLMUnavailableError as exc:
            log.warning("chat.web_fallback.llm_unavailable", error=str(exc))
            yield _sse("error", {"detail": "LLM non disponibile per la sintesi web"})
            return

        t_start = time.monotonic()
        n_tokens = 0
        try:
            async for chunk in llm.generate(prompt, max_new_tokens=220):
                n_tokens += 1
                yield _sse("token", {"text": chunk.text, "token_id": chunk.token_id})
        except Exception as exc:  # noqa: BLE001
            log.warning("chat.web_fallback.llm_failed", error=str(exc))
            yield _sse("error", {"detail": f"errore LLM: {exc}"})
            return

        # Append the source list as a final token so the user can verify.
        if sources_block:
            yield _sse("token", {"text": sources_block, "token_id": -1})

        elapsed = time.monotonic() - t_start
        yield _sse("done", {
            "conversation_id": convo_id_str,
            "tokens": n_tokens,
            "first_token_seconds": 0.0,
            "total_seconds": round(elapsed, 3),
            "tokens_per_second": round(n_tokens / max(elapsed, 0.001), 2),
            "routed": "web_search",
        })

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


__all__ = ["try_web_search"]
