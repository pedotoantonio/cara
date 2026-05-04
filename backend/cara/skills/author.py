"""Skill Author — cloud LLM that drafts a JSON skill plan from an unhandled
user message. Phase D of the Skill Factory v0.7
(see /opt/cara/docs/skill-factory-extension-prompt.md §3.3, §6).

Flow:
  user_message → build_prompt(capabilities) → Anthropic Claude → JSON →
    validate_skill_json() → SkillProposal | UnsupportedProposal | error

The cloud call is the only place CARA talks to a third-party LLM. Privacy:
only the user's last message + the capability registry leave the box —
no chat history, no other users, no file content. Audit log records the call.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import structlog

from cara.config import settings
from cara.skills.registry import PrimitiveSpec, list_primitives

log = structlog.get_logger(__name__)


# --- public types -------------------------------------------------------


class SkillAuthorError(RuntimeError):
    """Top-level Skill Author failure (provider, JSON parse, validation)."""


class SkillAuthorDisabledError(SkillAuthorError):
    """Either the env API key is missing or the admin flag is OFF."""


class SkillAuthorProviderError(SkillAuthorError):
    """The cloud LLM provider returned an error or timed out."""


class SkillAuthorValidationError(SkillAuthorError):
    """The model produced JSON but it doesn't conform to the schema."""

    def __init__(self, reasons: list[str], raw: str) -> None:
        self.reasons = reasons
        self.raw = raw
        super().__init__("; ".join(reasons))


@dataclass
class SkillProposal:
    """Validated JSON skill ready to be persisted as `status='pending'`."""

    name: str
    description: str
    intent_examples: list[str]
    slot_extraction: dict[str, Any]
    plan: dict[str, Any]
    response_template: str | None
    fallback_response: str | None


@dataclass
class UnsupportedProposal:
    """The model declared the request out-of-scope for the current registry."""

    reason: str
    missing_primitives: list[str] = field(default_factory=list)


# --- prompt -------------------------------------------------------------


DEFAULT_AUTHOR_PROMPT = """\
Sei "Skill Architect", un meta-agente di CARA — un assistente domestico \
self-hosted per la famiglia Pedoto. Il tuo compito: progettare una "skill" \
deterministica per gestire una richiesta utente che il sistema non ha ancora \
imparato a fare.

OUTPUT: SOLO un singolo oggetto JSON valido. NIENTE testo prima/dopo, NIENTE \
markdown, NIENTE commenti, NIENTE backticks. Solo `{ ... }`.

REGOLE:
1. Componi SOLO con primitive elencate sotto. Non inventare tool nuovi.
2. Identifica le SLOT della richiesta (es. "torta margherita" → dish:string).
   Per ogni slot definisci un metodo di estrazione: regex (preferito).
   Forma: "<slot>": {"method":"regex","pattern":"<regex Python>","group":1,"required":true}
3. Scrivi 5-8 intent_examples in italiano: 1 è il messaggio originale, gli \
   altri sono parafrasi naturali (varia verbi, preposizioni, ordine).
4. Il plan è una pipeline LINEARE di step. NO loop, NO branching, NO \
   condizionali. Ogni step può referenziare l'output dei precedenti via \
   {step_id.field} e gli slot via {slot_name}.
5. Ogni step ha esattamente: id (snake_case), tool (nome primitiva), args (oggetto).
6. Se la richiesta NON è risolvibile con le primitive disponibili, rispondi:
   {"unsupported": true, "reason": "<perché>", "missing_primitives": ["<nome1>", ...]}
7. response_template usa {slot} e {step.field}. Tono: caldo, breve, italiano.
8. fallback_response per quando il piano fallisce a metà.
9. Il `name` della skill deve essere snake_case ASCII (a-z, 0-9, underscore), \
   3-50 caratteri, descrittivo (es. "ricetta_to_spesa", "meteo_domani").

SCHEMA OUTPUT:
{
  "name": "snake_case_name",
  "description": "Cosa fa la skill, una frase.",
  "intent_examples": ["...", "...", "..."],
  "slot_extraction": {"<slot>": {"method":"regex","pattern":"...","group":1,"required":true}},
  "plan": {
    "steps": [
      {"id":"s1","tool":"<primitive>","args":{...}},
      {"id":"s2","tool":"<primitive>","args":{"x":"{s1.field}"}}
    ]
  },
  "response_template": "...",
  "fallback_response": "..."
}

PRIMITIVE DISPONIBILI:
{capability_listing}

CONTESTO:
- Utente: {user_role}
- Ultimi 3 turni: {recent_turns}

RICHIESTA UTENTE (la cosa che CARA non sa ancora fare):
"{user_message}"

PROGETTA. SOLO IL JSON.
"""


def build_capability_listing(primitives: list[PrimitiveSpec] | None = None) -> str:
    """Compact registry dump for the LLM menu. One primitive per line."""
    primitives = primitives if primitives is not None else list_primitives()
    lines: list[str] = []
    for p in primitives:
        args = ", ".join(f"{k}:{v}" for k, v in p.args_schema.items()) or "—"
        rets = ", ".join(f"{k}:{v}" for k, v in p.returns_schema.items()) or "—"
        lines.append(f"  - {p.name}({args}) → {{{rets}}}: {p.description}")
    return "\n".join(lines) if lines else "  (registry vuoto)"


def build_prompt(
    *,
    user_message: str,
    user_role: str = "parent",
    recent_turns: list[str] | None = None,
    capability_listing: str | None = None,
    template: str | None = None,
) -> str:
    """Substitute the prompt placeholders and return the full system text."""
    tpl = template if template is not None else DEFAULT_AUTHOR_PROMPT
    listing = (
        capability_listing if capability_listing is not None else build_capability_listing()
    )
    turns = recent_turns or []
    turns_text = "; ".join(turns[-3:]) if turns else "(nessuno)"
    return (
        tpl.replace("{capability_listing}", listing)
        .replace("{user_role}", user_role)
        .replace("{recent_turns}", turns_text)
        .replace("{user_message}", user_message.replace('"', "'"))
    )


# --- JSON parsing & validation -----------------------------------------


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _strip_to_json(raw: str) -> str:
    """Models occasionally add fences or stray prose despite instructions —
    pull out the JSON object."""
    s = raw.strip()
    m = _JSON_FENCE_RE.search(s)
    if m:
        s = m.group(1).strip()
    # Trim anything before first `{` and after last `}` (best-effort).
    first = s.find("{")
    last = s.rfind("}")
    if first >= 0 and last > first:
        s = s[first : last + 1]
    return s


_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,49}$")


def validate_skill_json(
    data: dict[str, Any],
) -> tuple[SkillProposal | UnsupportedProposal | None, list[str]]:
    """Returns either a proposal (typed) or `(None, reasons)` if invalid.

    `unsupported=true` short-circuits to UnsupportedProposal.
    """
    reasons: list[str] = []

    if data.get("unsupported") is True:
        return (
            UnsupportedProposal(
                reason=str(data.get("reason") or "(non specificato)"),
                missing_primitives=list(data.get("missing_primitives") or []),
            ),
            [],
        )

    name = str(data.get("name") or "").strip()
    if not _NAME_RE.match(name):
        reasons.append(
            f"`name` non valido: {name!r} (snake_case 3-50 chars, [a-z0-9_])"
        )
    description = str(data.get("description") or "").strip()
    if not description:
        reasons.append("`description` vuota")

    examples = data.get("intent_examples") or []
    if not isinstance(examples, list) or not all(isinstance(e, str) for e in examples):
        reasons.append("`intent_examples` deve essere lista di stringhe")
        examples = []
    if len(examples) < 1:
        reasons.append("almeno 1 intent_example richiesto")
    if len(examples) > 20:
        reasons.append("troppi intent_examples (cap 20)")

    slot_extraction = data.get("slot_extraction") or {}
    if not isinstance(slot_extraction, dict):
        reasons.append("`slot_extraction` deve essere oggetto")
        slot_extraction = {}

    declared_slots: set[str] = set()
    for slot_name, spec in slot_extraction.items():
        if not isinstance(spec, dict):
            reasons.append(f"slot {slot_name!r}: spec non valida (atteso oggetto)")
            continue
        method = spec.get("method", "regex")
        if method != "regex":
            reasons.append(
                f"slot {slot_name!r}: method {method!r} non supportato (solo 'regex')"
            )
            continue
        pattern = spec.get("pattern", "")
        if not isinstance(pattern, str) or not pattern:
            reasons.append(f"slot {slot_name!r}: pattern mancante")
            continue
        try:
            re.compile(pattern)
        except re.error as exc:
            reasons.append(f"slot {slot_name!r}: regex invalida ({exc})")
            continue
        declared_slots.add(slot_name)

    plan = data.get("plan") or {}
    if not isinstance(plan, dict):
        reasons.append("`plan` deve essere oggetto")
        plan = {}
    steps = plan.get("steps") or []
    if not isinstance(steps, list) or not steps:
        reasons.append("`plan.steps` deve essere lista non vuota")
        steps = []

    seen_step_ids: set[str] = set()
    referenced_steps: set[str] = set()
    referenced_slots: set[str] = set()

    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            reasons.append(f"step #{idx}: non è oggetto")
            continue
        step_id = str(step.get("id") or "").strip()
        tool_name = str(step.get("tool") or "").strip()
        args = step.get("args") or {}

        if not _NAME_RE.match(step_id) and not (step_id and step_id.replace("_", "").isalnum()):
            reasons.append(f"step #{idx}: id {step_id!r} invalido")
            continue
        if step_id in seen_step_ids:
            reasons.append(f"step #{idx}: id duplicato {step_id!r}")
        seen_step_ids.add(step_id)

        from cara.skills.registry import get_primitive  # local to avoid cycle

        spec = get_primitive(tool_name)
        if spec is None:
            reasons.append(f"step {step_id!r}: primitiva sconosciuta {tool_name!r}")
            continue

        if not isinstance(args, dict):
            reasons.append(f"step {step_id!r}: args deve essere oggetto")
            continue

        # Args keys must be a subset of the primitive's declared schema.
        unknown_args = set(args) - set(spec.args_schema)
        if unknown_args:
            reasons.append(
                f"step {step_id!r}: args sconosciuti per {tool_name!r}: {sorted(unknown_args)}"
            )

        # Walk arg values for {ref} placeholders so we can sanity-check them.
        for ref in _collect_refs(args):
            head = ref.split(".")[0]
            if head in declared_slots:
                referenced_slots.add(head)
            elif head in seen_step_ids and head != step_id:
                referenced_steps.add(head)
            else:
                reasons.append(
                    f"step {step_id!r}: riferimento {{{ref}}} non risolvibile "
                    f"(slot/step precedente non trovato)"
                )

    # Slot/example sanity: warn if a declared slot is never referenced.
    unused_slots = declared_slots - referenced_slots
    if unused_slots and steps:
        # Soft warning, don't fail validation — the model may legitimately
        # extract a slot only for the response_template.
        log.info("skill.author.validate.slot_unused", slots=list(unused_slots))

    response_template = data.get("response_template")
    if response_template is not None and not isinstance(response_template, str):
        reasons.append("`response_template` deve essere stringa o null")
        response_template = None
    fallback_response = data.get("fallback_response")
    if fallback_response is not None and not isinstance(fallback_response, str):
        reasons.append("`fallback_response` deve essere stringa o null")
        fallback_response = None

    if reasons:
        return (None, reasons)

    return (
        SkillProposal(
            name=name,
            description=description,
            intent_examples=list(examples),
            slot_extraction=dict(slot_extraction),
            plan={"steps": steps},
            response_template=response_template,
            fallback_response=fallback_response,
        ),
        [],
    )


_REF_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}")


def _collect_refs(value: Any) -> list[str]:
    """Walk strings/lists/dicts and collect every `{ref}` placeholder path."""
    found: list[str] = []
    if isinstance(value, str):
        for m in _REF_RE.finditer(value):
            found.append(m.group(1))
    elif isinstance(value, list):
        for v in value:
            found.extend(_collect_refs(v))
    elif isinstance(value, dict):
        for v in value.values():
            found.extend(_collect_refs(v))
    return found


# --- provider call ------------------------------------------------------


async def _call_anthropic(prompt: str, *, model: str, max_tokens: int, timeout: float) -> str:
    """Single Anthropic API call. Lazy import keeps the package optional at
    boot — if ANTHROPIC_API_KEY is empty we never instantiate the client."""
    try:
        from anthropic import AsyncAnthropic  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - defensive
        raise SkillAuthorProviderError(
            "anthropic package non installato"
        ) from exc

    api_key = settings.anthropic_api_key
    if not api_key:
        raise SkillAuthorDisabledError(
            "ANTHROPIC_API_KEY non configurata in .env"
        )

    client = AsyncAnthropic(api_key=api_key, timeout=timeout)
    try:
        msg = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # noqa: BLE001
        raise SkillAuthorProviderError(f"anthropic call failed: {exc}") from exc

    parts = []
    for block in msg.content or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    text = "".join(parts).strip()
    if not text:
        raise SkillAuthorProviderError("anthropic returned empty content")
    return text


# --- top-level entry ---------------------------------------------------


async def author_skill(
    *,
    user_message: str,
    user_role: str = "parent",
    recent_turns: list[str] | None = None,
    prompt_override: str | None = None,
    provider_override: str | None = None,
    model_override: str | None = None,
    max_retries: int | None = None,
) -> tuple[SkillProposal | UnsupportedProposal, dict[str, Any]]:
    """Ask the cloud LLM to draft a skill plan for `user_message`.

    Returns `(proposal, telemetry)` where `proposal` is one of
    `SkillProposal | UnsupportedProposal` and `telemetry` carries the raw
    response, retries, and provider info for the audit log.

    Raises `SkillAuthorDisabledError` if the API key is missing,
    `SkillAuthorProviderError` if the cloud call fails after all retries,
    `SkillAuthorValidationError` if the JSON never validates.
    """
    if not user_message or not user_message.strip():
        raise SkillAuthorValidationError(["user_message vuoto"], "")

    provider = (provider_override or settings.skill_author_provider or "").strip().lower()
    if provider in ("disabled", ""):
        raise SkillAuthorDisabledError(f"provider {provider!r} non abilitato")

    model = (model_override or settings.skill_author_model or "").strip()
    if not model:
        raise SkillAuthorDisabledError("nessun modello configurato")

    retries = settings.skill_author_max_retries if max_retries is None else max_retries
    retries = max(0, int(retries))

    prompt = build_prompt(
        user_message=user_message,
        user_role=user_role,
        recent_turns=recent_turns,
        template=prompt_override,
    )

    last_reasons: list[str] = []
    last_raw = ""
    attempts = 0
    while attempts <= retries:
        attempts += 1
        log.info(
            "skill.author.call",
            provider=provider,
            model=model,
            attempt=attempts,
            user_message_len=len(user_message),
        )
        raw = await _call_anthropic(
            prompt,
            model=model,
            max_tokens=settings.skill_author_max_tokens,
            timeout=settings.skill_author_timeout_seconds,
        )
        last_raw = raw
        try:
            data = json.loads(_strip_to_json(raw))
        except json.JSONDecodeError as exc:
            last_reasons = [f"JSON invalido: {exc}"]
            log.warning(
                "skill.author.parse_failed", attempt=attempts, error=str(exc),
                preview=raw[:200],
            )
            # Append a corrective hint to the prompt for the retry.
            prompt += (
                "\n\nIl tuo output precedente non era JSON valido — riprova,"
                " questa volta SOLO l'oggetto JSON e nient'altro."
            )
            continue

        proposal, reasons = validate_skill_json(data)
        if proposal is not None:
            telemetry = {
                "provider": provider,
                "model": model,
                "attempts": attempts,
                "raw_chars": len(raw),
            }
            log.info(
                "skill.author.success",
                provider=provider,
                model=model,
                attempts=attempts,
                kind="unsupported" if isinstance(proposal, UnsupportedProposal) else "skill",
            )
            return proposal, telemetry

        last_reasons = reasons
        log.warning(
            "skill.author.validate_failed",
            attempt=attempts,
            reasons=reasons[:5],
        )
        prompt += (
            "\n\nIl JSON precedente non rispettava lo schema. Errori riscontrati:\n- "
            + "\n- ".join(reasons[:8])
            + "\nRiprova rispettando ESATTAMENTE lo schema."
        )

    raise SkillAuthorValidationError(last_reasons, last_raw)
