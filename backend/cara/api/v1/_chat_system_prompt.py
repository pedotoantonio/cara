"""System prompt builder — segmented for KV-cache efficiency (Step 1.5).

Pre-this-step every chat turn rebuilt the full system prompt as one
giant blob. RKLLM's prompt cache reuses prefill *only* when the prefix
matches byte-for-byte, so injecting today's date or a top-k fact at the
very start of the prompt invalidated the cache on every turn.

This builder splits the prompt into three layered segments, ordered
from most-stable to least-stable:

  1. **base** — the persona system prompt the admin set in
     admin_settings (`llm_system_prompt`). Changes maybe once a month.
     This is the prefix the KV cache locks on.

  2. **tone** — the per-role tone directive (default / privacy /
     playful) from `_chat_prompt.TONE_DIRECTIVE`. Changes per-role
     but identical across turns of the same role.

  3. **facts** — top-k semantic facts retrieved for *this* user / *this*
     conversation, plus the runtime context (date, time, days-to-Xmas).
     This is the volatile tail — different every turn, and it sits at
     the end so it doesn't poison the cacheable prefix.

The composer returns the assembled string PLUS a fingerprint of the
stable prefix so the chat layer can decide whether to flush the KV
cache (e.g. when the admin edits `llm_system_prompt` mid-session,
the fingerprint changes and `kv_cache.flush_one(conv_id)` runs).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

from cara.api.v1._chat_prompt import TONE_DIRECTIVE, runtime_context_message


@dataclass
class SystemPromptSegments:
    """Four layers of the system prompt + the stable-prefix fingerprint.

    Ordered most-stable → least-stable so KV-cache prefill survives:

      base      → admin system prompt (~monthly change)
      tone      → tone directive (~per-role)
      persona   → user's longitudinal profile (~nightly rebuild) ← Ondata β
      facts     → top-k facts + runtime context (~per-turn)

    `persona` is in the stable prefix because it changes once per night
    per user; the first chat turn after a rebuild pays one full prefill
    (~200ms TTFT), every subsequent turn that day is cached.
    """

    base: str
    tone: str
    facts: str
    persona: str = ""

    def assemble(self) -> str:
        parts = [self.base.rstrip()]
        if self.tone:
            parts.append(self.tone.rstrip())
        if self.persona:
            parts.append(self.persona.rstrip())
        if self.facts:
            parts.append(self.facts.rstrip())
        return "\n\n".join(p for p in parts if p)

    def stable_prefix(self) -> str:
        """Concatenation of the segments that survive across turns —
        what the KV cache effectively prefills on. `facts` is excluded
        because it's regenerated per turn."""
        return (
            f"{self.base.rstrip()}\n\n"
            f"{self.tone.rstrip()}\n\n"
            f"{self.persona.rstrip()}"
        ).rstrip()

    def fingerprint(self) -> str:
        """Short SHA-1 of the stable prefix; used by the chat layer to
        detect mid-session prompt changes and flush the KV cache."""
        return hashlib.sha1(
            self.stable_prefix().encode("utf-8")
        ).hexdigest()[:16]


def build_persona_block(persona_markdown: str | None, *, user_name: str | None = None) -> str:
    """Wrap the persona markdown in a labelled section the model can spot.

    Skipped (returns "") if `persona_markdown` is empty or None. Caller
    is expected to have already passed the confidence / status filters
    (see `learning.persona_profiler.get_for_prompt_injection`).
    """
    md = (persona_markdown or "").strip()
    if not md:
        return ""
    header = (
        f"## CHI È {user_name.upper()} (profilo longitudinale)"
        if user_name
        else "## CHI È L'UTENTE (profilo longitudinale)"
    )
    return (
        f"{header}\n"
        f"{md}\n"
        "Usa questo profilo per dare risposte coerenti con la persona; "
        "non riportarlo testualmente all'utente."
    )


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_facts_block(
    facts: Iterable[str] | None,
    *,
    user_name: str | None = None,
) -> str:
    """Format the top-k facts retrieved for the current request.

    `facts` are short factual sentences ("È allergico ai pomodori",
    "Non gli piace la pasta al sugo"). We render them as a bulleted
    list so the model can scan them quickly without confusing them
    with conversation turns.

    `user_name` (optional) is interpolated as a header so the model
    knows whose facts these are. Skipped in privacy mode (the chat
    layer simply passes user_name=None then).
    """
    items = [f.strip() for f in (facts or []) if f and f.strip()]
    if not items:
        return ""
    header = (
        f"## FATTI SU {user_name.upper()}"
        if user_name
        else "## FATTI RILEVANTI"
    )
    body = "\n".join(f"- {f}" for f in items)
    return (
        f"{header}\n"
        f"{body}\n"
        "Tieni conto di questi fatti se sono pertinenti alla domanda. "
        "Non riportarli a meno che non sia utile, e non chiedere conferma di cose già scritte qui."
    )


def build_segments(
    *,
    base_prompt: str,
    tone_key: str = "default",
    user_facts: Iterable[str] | None = None,
    user_name: str | None = None,
    persona_markdown: str | None = None,
    include_runtime_context: bool = True,
) -> SystemPromptSegments:
    """Compose the four segments. Pure function — easily unit-testable.

    `base_prompt`: the admin-configured system prompt
                   (`admin_settings.llm_system_prompt` or the env
                   default in `cara.config.settings.llm_system_prompt`).

    `tone_key`: lookup into `TONE_DIRECTIVE`. Unknown keys fall back to
                 the default empty string (no tone overlay).

    `user_facts`: iterable of fact texts retrieved from semantic memory
                   (top-k via embeddings). Empty iterable → no facts
                   block emitted.

    `persona_markdown`: Ondata β — the longitudinal profile from
                         `learning.persona_profiler`. Already validated
                         (confidence ≥ threshold, status='ok') and
                         truncated to PROFILE_MAX_CHARS by the caller.
                         None / empty → no persona block emitted.

    `include_runtime_context`: append today's date / time / days-to-Xmas
                                to the facts block. Default True.
    """
    base = base_prompt.strip()
    tone = TONE_DIRECTIVE.get(tone_key, "").strip()
    persona = build_persona_block(persona_markdown, user_name=user_name)

    # Volatile tail.
    parts: list[str] = []
    facts_block = build_facts_block(user_facts, user_name=user_name)
    if facts_block:
        parts.append(facts_block)
    if include_runtime_context:
        parts.append(runtime_context_message())
    facts = "\n\n".join(parts)

    return SystemPromptSegments(base=base, tone=tone, facts=facts, persona=persona)
