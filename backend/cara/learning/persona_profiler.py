"""Persona Profiler — map-reduce LLM longitudinal user profile.

Lumo-conversion Ondata β. The big memory win on the 1.5B.

The 1.5B model has no longitudinal coherence: at every chat turn it only
sees the recent N messages of the current conversation. Anything older
— or anything from a different conversation entirely — is lost.

This module materialises, for each user, a Markdown profile fused from
the *entire* message history, and injects it into the system prompt
every turn. The model gets continuity it physically cannot derive from
its own context window.

How it builds the profile (Lumo's pattern):

  1. EXTRACT — given a chunk of N messages, ask the LLM to extract
     identity / family / work / habits / tastes / health / values /
     mood / relationships into fixed H3 sections, marking each claim
     either **STABILE** (durable) or **EPISODICO** (time-bound, dated).
     Add ## Contraddizioni and ## Lacune sections. End with a
     'Confidenza: X%' line.

  2. MERGE — given the existing consolidated profile + the fresh
     extraction, fuse into one updated profile without duplication,
     keeping the most recent value on conflict, decaying EPISODICO
     claims older than 30 days.

Both prompts are token-aware: we chunk so each EXTRACT call fits in
~1500 tokens of input + ~800 tokens of output. The MERGE call gets the
old profile + the new fragment; if the sum overflows, we run MERGE
with a 'comprimere a N token' hint.

Costs (1.5B on RK3588 NPU, observed during dev):
  - EXTRACT one chunk of 50 messages: 8-12s
  - MERGE: 4-8s
  - Typical incremental rebuild (30 new messages): 1 chunk + 1 merge ≈ 15-20s
  - Initial build for 300-message corpus: 6 chunks + 6 merges ≈ 2-3 min
  - All on the same NPU lock as chat. Scheduled at 03:15 — silent hour.

Reads:
  - `cara.models.Message` history per user, ascending by id.
  - `cara.models.PersonaProfile.last_message_id_consumed` as watermark.
Writes:
  - `cara.models.PersonaProfile` upserted with new markdown, confidence,
    sections (parsed), last_built_at, last_message_id_consumed.

Public API (only what callers need):

    await rebuild_for_user(session, llm, user_id)         # nightly + on-demand
    md = await get_for_prompt_injection(session, user_id) # chat hot path

The chat layer calls `get_for_prompt_injection` synchronously per turn —
it's a single DB SELECT, no LLM. Cheap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.ai.llm import LLMService, LLMUnavailableError
from cara.models import Message, PersonaProfile, User


log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Chars-per-token estimate (Qwen2.5 IT tokenizer): ~2.5 chars/token.
# Conservative side — better to chunk slightly small than overflow.
_CHARS_PER_TOKEN = 2.5

# EXTRACT call budget. Input prompt envelope ~600 tokens + chunk
# (variable) + output 800. RKLLM context window is set to 4096 in
# default config; leave headroom.
EXTRACT_CHUNK_MAX_TOKENS = 1500
EXTRACT_OUTPUT_MAX_TOKENS = 900

# MERGE call budget. Old profile (capped at 1200 tokens by injection
# logic) + new fragment (up to 800) + envelope (300) + output (800).
MERGE_OUTPUT_MAX_TOKENS = 900

# Maximum profile size persisted. Anything larger triggers a second
# MERGE pass with 'comprimere a N tokens'.
PROFILE_MAX_CHARS = 3200      # ~800 tokens, the prompt-injection cap
PROFILE_HARD_CAP_CHARS = 8000  # absolute ceiling, also a sanity guard

# Confidence floor: profiles below this are stored but NOT injected
# into the prompt (we'd rather skip than mislead the LLM).
MIN_CONFIDENCE_FOR_INJECTION = 60.0

# Decay window for EPISODICO claims when re-injecting into MERGE.
EPISODIC_DECAY_DAYS = 30


# ---------------------------------------------------------------------------
# Prompts (Italian)
# ---------------------------------------------------------------------------

_EXTRACT_SYSTEM = (
    "Sei l'analista di profili utente di CARA. Il tuo compito è estrarre, "
    "dai messaggi che seguono, tutto ciò che caratterizza {user_name} come "
    "persona.\n\n"
    "REGOLE DI OUTPUT (rispetta TUTTE):\n"
    "1. Markdown con sezioni H3 fisse in questo ordine: "
    "## Identità, ## Famiglia, ## Lavoro, ## Abitudini, ## Gusti, "
    "## Salute, ## Valori, ## Stato emotivo, ## Relazioni.\n"
    "2. In ogni sezione, distingui chiaramente:\n"
    "   - **STABILE**: tratti che resistono nel tempo (allergie, mestiere, "
    "hobby ricorrenti, valori).\n"
    "   - **EPISODICO**: cose di questo periodo (sentimenti recenti, "
    "eventi una-tantum). Anteponi sempre la data ISO in formato "
    "[YYYY-MM-DD], es. '[2026-05-20] giornata pesante al lavoro'.\n"
    "3. Aggiungi sempre, in fondo:\n"
    "   - ## Contraddizioni: affermazioni dell'utente che si contraddicono "
    "fra messaggi diversi (omettere la sezione se non ce ne sono).\n"
    "   - ## Lacune: cose importanti che NON sai ancora (omettere se "
    "saturate).\n"
    "4. Chiudi con una riga finale: 'Confidenza: X%' dove X è la tua stima "
    "(0-100) di quanto bene conosci {user_name}.\n"
    "5. NON inventare. Se una sezione è vuota scrivi 'Sconosciuto'.\n"
    "6. NON aggiungere intro o spiegazioni, solo il Markdown.\n"
)

_EXTRACT_USER = (
    "Messaggi di {user_name} (ordine cronologico, dal più vecchio):\n\n"
    "{chunk}\n\n"
    "Estrai ora il profilo seguendo le regole."
)

_MERGE_SYSTEM = (
    "Hai due profili di {user_name}: il vecchio (consolidato) e una nuova "
    "estrazione fresca. Fondili in un UNICO profilo aggiornato.\n\n"
    "REGOLE DI OUTPUT (rispetta TUTTE):\n"
    "1. Stessa struttura del profilo vecchio (sezioni H3 fisse).\n"
    "2. Per ogni claim STABILE: tieni la versione più recente se in "
    "conflitto; se il conflitto è notevole spostalo in ## Contraddizioni.\n"
    "3. Per ogni claim EPISODICO: tieni gli ultimi {decay_days} giorni "
    "(la data ISO è anteposta). Scarta i più vecchi senza menzionarli.\n"
    "4. Risolvi duplicati: stesso fatto in formulazioni diverse = UN solo "
    "bullet, scegli la più precisa.\n"
    "5. Aggiorna ## Lacune: rimuovi quelle ora risolte dai nuovi messaggi, "
    "aggiungi quelle nuove emerse.\n"
    "6. Aggiorna 'Confidenza: X%' all'ultima riga (media pesata vecchio+nuovo, "
    "ma se il nuovo conferma chiaramente alza la confidenza).\n"
    "7. Massimo {budget_tokens} token totali. Se il profilo è più lungo, "
    "comprimi PRIMA gli EPISODICI vecchi, POI accorcia gli STABILI "
    "ridondanti.\n"
    "8. NON aggiungere intro o spiegazioni, solo il Markdown finale.\n"
)

_MERGE_USER = (
    "## Profilo vecchio (consolidato)\n{old_profile}\n\n"
    "## Estrazione nuova\n{new_fragment}\n\n"
    "Fondi i due ora."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _approx_tokens(text: str) -> int:
    return int(len(text) / _CHARS_PER_TOKEN) + 1


def chunk_messages_token_aware(
    messages: list[Message], max_tokens_per_chunk: int = EXTRACT_CHUNK_MAX_TOKENS
) -> list[list[Message]]:
    """Split messages into chunks each ≤ max_tokens_per_chunk.

    Greedy from oldest: accumulate until next message would overflow,
    then start a new chunk. Never splits a single message — a single
    very long message gets its own chunk (and we trust the LLM to
    still produce something useful).
    """
    chunks: list[list[Message]] = []
    current: list[Message] = []
    current_tokens = 0
    for m in messages:
        m_tokens = _approx_tokens(m.content or "")
        if current and current_tokens + m_tokens > max_tokens_per_chunk:
            chunks.append(current)
            current = []
            current_tokens = 0
        current.append(m)
        current_tokens += m_tokens
    if current:
        chunks.append(current)
    return chunks


def _format_chunk(messages: list[Message]) -> str:
    """Pretty-format a chunk for the EXTRACT prompt.

    Format:
        [2026-05-20 14:32] U: ho parlato con il dottore...
        [2026-05-20 14:33] A: ok, vuoi che metta un promemoria?
        [2026-05-20 14:33] U: sì, fra una settimana

    Truncate any single message > 800 chars (we don't need full files
    pasted into the profiler — just signals about the person).
    """
    lines: list[str] = []
    for m in messages:
        if m.role not in ("user", "assistant"):
            continue
        ts = m.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M") if m.created_at else "????-??-??"
        role_label = "U" if m.role == "user" else "A"
        content = (m.content or "").strip()
        if len(content) > 800:
            content = content[:800] + " …"
        lines.append(f"[{ts}] {role_label}: {content}")
    return "\n".join(lines)


def _extract_confidence(markdown: str) -> float | None:
    """Pull the 'Confidenza: X%' line out of the LLM output."""
    m = re.search(r"Confidenza:\s*(\d{1,3})\s*%", markdown)
    if not m:
        return None
    try:
        v = float(m.group(1))
        return max(0.0, min(100.0, v))
    except ValueError:
        return None


def _parse_sections(markdown: str) -> dict[str, Any]:
    """Best-effort parse: split by H3, group STABILE vs EPISODICO bullets.

    The chat layer doesn't use this — it just injects the raw markdown.
    But the admin UI gets a nice section-by-section card view from it.
    """
    sections: dict[str, Any] = {}
    current_section: str | None = None
    current_bullets: list[str] = []
    for line in markdown.splitlines():
        h3 = re.match(r"^##+\s+(.+?)\s*$", line)
        if h3:
            if current_section is not None:
                sections[current_section] = _bullets_to_buckets(current_bullets)
            current_section = h3.group(1).strip()
            current_bullets = []
            continue
        # Bullet detection: leading "- " or "* " (single character + space).
        # `lstrip("-* ")` would eat the bold marker stars too, so we use a
        # more precise regex strip that ONLY removes the bullet marker.
        bullet_match = re.match(r"^\s*[-*]\s+(.*)$", line)
        if bullet_match:
            current_bullets.append(bullet_match.group(1).strip())
    if current_section is not None:
        sections[current_section] = _bullets_to_buckets(current_bullets)
    return sections


def _bullets_to_buckets(bullets: list[str]) -> dict[str, Any]:
    """Sort bullets into STABILE / EPISODICO buckets.

    Accepts both `**STABILE**` (bold) and `STABILE` (plain), with or
    without surrounding markdown. Case-insensitive.
    """
    stable: list[str] = []
    episodic: list[dict[str, str]] = []
    # Marker can appear as **STABILE**, *STABILE*, STABILE:, [STABILE], etc.
    stable_re = re.compile(r"(?:\*\*|__|\*|_|\[)?\s*STABILE\s*(?:\*\*|__|\*|_|\])?\s*[:\-]?\s*", re.I)
    episodic_re = re.compile(r"(?:\*\*|__|\*|_|\[)?\s*EPISODICO\s*(?:\*\*|__|\*|_|\])?\s*[:\-]?\s*", re.I)
    date_re = re.compile(r"\[(\d{4}-\d{2}-\d{2})\]\s*(.+)")
    for b in bullets:
        b_clean = b.strip()
        if not b_clean:
            continue
        if re.search(r"\bSTABILE\b", b_clean, re.I):
            txt = stable_re.sub("", b_clean, count=1).strip()
            stable.append(txt or b_clean)
        elif re.search(r"\bEPISODICO\b", b_clean, re.I):
            txt = episodic_re.sub("", b_clean, count=1).strip()
            d = date_re.match(txt)
            if d:
                episodic.append({"date": d.group(1), "text": d.group(2)})
            else:
                episodic.append({"date": "", "text": txt or b_clean})
        else:
            stable.append(b_clean)
    return {"stable": stable, "episodic": episodic}


def _truncate_to_chars(text: str, max_chars: int) -> str:
    """Hard cap on profile size. Truncate at the last full line."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    nl = cut.rfind("\n")
    if nl > max_chars * 0.8:
        cut = cut[:nl]
    return cut + "\n\n[…profilo troncato per limite di lunghezza]"


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------


@dataclass
class ProfileFragment:
    """Output of one EXTRACT call on one chunk of messages."""
    markdown: str
    confidence: float | None


async def _llm_call(
    llm: LLMService,
    *,
    system: str,
    user: str,
    max_new_tokens: int,
) -> str:
    """Wrap LLM.generate as a one-shot collect.

    The persona builder doesn't need streaming — it just needs the
    final text. We compose a Qwen2.5-style chat template manually
    (the same one `_chat_prompt.render_qwen_prompt` produces) and
    drain the async iterator.
    """
    prompt = (
        f"<|im_start|>system\n{system}<|im_end|>\n"
        f"<|im_start|>user\n{user}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )
    chunks: list[str] = []
    async for tok in llm.generate(prompt, max_new_tokens=max_new_tokens):
        chunks.append(tok.text)
    return "".join(chunks).strip()


async def extract_from_chunk(
    llm: LLMService, user_name: str, chunk: list[Message]
) -> ProfileFragment:
    """Run EXTRACT on a single chunk. Returns the raw fragment Markdown."""
    chunk_text = _format_chunk(chunk)
    if not chunk_text.strip():
        return ProfileFragment(markdown="", confidence=None)

    system = _EXTRACT_SYSTEM.format(user_name=user_name)
    user_msg = _EXTRACT_USER.format(user_name=user_name, chunk=chunk_text)
    out = await _llm_call(
        llm, system=system, user=user_msg, max_new_tokens=EXTRACT_OUTPUT_MAX_TOKENS
    )
    conf = _extract_confidence(out)
    return ProfileFragment(markdown=out, confidence=conf)


async def merge(
    llm: LLMService,
    *,
    user_name: str,
    old_profile: str,
    new_fragment: str,
    budget_tokens: int = 800,
) -> str:
    """Fuse old + new into a single updated profile."""
    if not old_profile.strip():
        # Nothing to merge — the new fragment IS the profile (after cap).
        return _truncate_to_chars(new_fragment, PROFILE_MAX_CHARS)
    if not new_fragment.strip():
        return old_profile

    system = _MERGE_SYSTEM.format(
        user_name=user_name,
        decay_days=EPISODIC_DECAY_DAYS,
        budget_tokens=budget_tokens,
    )
    user_msg = _MERGE_USER.format(
        old_profile=old_profile, new_fragment=new_fragment
    )
    out = await _llm_call(
        llm, system=system, user=user_msg, max_new_tokens=MERGE_OUTPUT_MAX_TOKENS
    )
    return _truncate_to_chars(out, PROFILE_HARD_CAP_CHARS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def rebuild_for_user(
    session: AsyncSession,
    llm: LLMService,
    user_id: int,
    *,
    full_rebuild: bool = False,
    max_chunks: int = 10,
) -> dict[str, Any]:
    """Rebuild the persona profile for one user.

    `full_rebuild=False` (default): incremental — only messages with
    id > `last_message_id_consumed` are extracted, then merged into the
    existing profile.

    `full_rebuild=True`: start from scratch. Useful when the prompts
    change shape and the old profile would be in a different schema.

    `max_chunks`: cap on EXTRACT calls per invocation, so a user with
    50k messages doesn't monopolise the NPU for an hour. The
    watermark still moves forward by the number of chunks consumed —
    the rest is picked up on the next nightly tick.

    Returns a status dict:
      {
        "status": "ok" | "skipped_no_messages" | "low_confidence" | "failed",
        "chunks_processed": N,
        "messages_consumed": M,
        "confidence": X,
        "markdown_chars": L,
        "error": "..." (only on failed),
      }
    """
    user = await session.get(User, user_id)
    if user is None:
        return {"status": "failed", "error": f"user {user_id} not found"}

    user_name = (user.full_name or user.email.split("@")[0]).split()[0]

    # Load (or create) the profile row.
    profile = await session.get(PersonaProfile, user_id)
    if profile is None:
        profile = PersonaProfile(user_id=user_id, markdown="")
        session.add(profile)

    # Determine watermark.
    if full_rebuild:
        watermark = 0
        old_profile = ""
    else:
        watermark = profile.last_message_id_consumed or 0
        old_profile = profile.markdown or ""

    # Fetch new messages (user role only — assistant messages confuse
    # the extractor about WHOSE traits we're profiling).
    msgs_q = (
        select(Message)
        .where(
            Message.user_id == user_id,
            Message.id > watermark,
            Message.role == "user",
        )
        .order_by(Message.id.asc())
    )
    msgs = (await session.execute(msgs_q)).scalars().all()
    if not msgs:
        log.info("persona.rebuild.skipped",
                 user_id=user_id, reason="no new messages")
        return {
            "status": "skipped_no_messages",
            "chunks_processed": 0,
            "messages_consumed": 0,
            "confidence": profile.confidence,
            "markdown_chars": len(profile.markdown or ""),
        }

    # Chunk and process.
    chunks = chunk_messages_token_aware(msgs)
    chunks = chunks[:max_chunks]

    log.info("persona.rebuild.start",
             user_id=user_id, user_name=user_name,
             watermark=watermark, n_messages=len(msgs),
             n_chunks=len(chunks))

    try:
        current_profile = old_profile
        last_confidence: float | None = profile.confidence
        for i, chunk in enumerate(chunks, start=1):
            fragment = await extract_from_chunk(llm, user_name, chunk)
            if not fragment.markdown.strip():
                continue
            current_profile = await merge(
                llm,
                user_name=user_name,
                old_profile=current_profile,
                new_fragment=fragment.markdown,
            )
            if fragment.confidence is not None:
                last_confidence = fragment.confidence
            log.info("persona.rebuild.chunk_done",
                     user_id=user_id, chunk=i, total=len(chunks),
                     fragment_chars=len(fragment.markdown),
                     fragment_confidence=fragment.confidence)

        new_watermark = chunks[-1][-1].id if chunks and chunks[-1] else watermark

        # If still too long, run a compression-merge pass.
        if len(current_profile) > PROFILE_MAX_CHARS:
            current_profile = await merge(
                llm,
                user_name=user_name,
                old_profile=current_profile,
                new_fragment="",
                budget_tokens=int(PROFILE_MAX_CHARS / _CHARS_PER_TOKEN),
            )

        sections = _parse_sections(current_profile)
        confidence = last_confidence if last_confidence is not None else _extract_confidence(current_profile)

        status = "ok"
        if confidence is not None and confidence < MIN_CONFIDENCE_FOR_INJECTION:
            status = "low_confidence"

        profile.markdown = current_profile
        profile.confidence = confidence
        profile.sections = sections
        profile.last_message_id_consumed = new_watermark
        profile.last_status = status
        profile.last_error = None
        profile.last_built_at = datetime.now(timezone.utc)
        profile.updated_at = datetime.now(timezone.utc)
        session.add(profile)
        await session.flush()

        log.info("persona.rebuild.done",
                 user_id=user_id, status=status,
                 markdown_chars=len(current_profile),
                 confidence=confidence, new_watermark=new_watermark)
        return {
            "status": status,
            "chunks_processed": len(chunks),
            "messages_consumed": len(msgs),
            "confidence": confidence,
            "markdown_chars": len(current_profile),
        }

    except LLMUnavailableError as exc:
        log.warning("persona.rebuild.llm_unavailable",
                    user_id=user_id, error=str(exc))
        profile.last_status = "failed"
        profile.last_error = f"LLM unavailable: {exc}"[:500]
        session.add(profile)
        await session.flush()
        return {"status": "failed", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — guard nightly job
        log.exception("persona.rebuild.failed", user_id=user_id)
        profile.last_status = "failed"
        profile.last_error = f"{type(exc).__name__}: {exc}"[:500]
        session.add(profile)
        await session.flush()
        return {"status": "failed", "error": str(exc)}


async def get_for_prompt_injection(
    session: AsyncSession, user_id: int, *, max_chars: int = PROFILE_MAX_CHARS
) -> str | None:
    """Return the markdown to inject into the chat system prompt.

    Returns None if:
      - no profile row exists,
      - profile is empty,
      - last_status is 'failed' or 'low_confidence',
      - confidence is below MIN_CONFIDENCE_FOR_INJECTION.

    Otherwise returns the markdown truncated at max_chars. Cheap —
    single PK SELECT, no LLM call. Called once per chat turn.
    """
    profile = await session.get(PersonaProfile, user_id)
    if profile is None:
        return None
    if not profile.markdown or not profile.markdown.strip():
        return None
    if profile.last_status in ("failed", "low_confidence"):
        return None
    if profile.confidence is not None and profile.confidence < MIN_CONFIDENCE_FOR_INJECTION:
        return None
    return _truncate_to_chars(profile.markdown.strip(), max_chars)
