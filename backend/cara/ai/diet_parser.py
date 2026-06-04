"""Meal-text parser for the diet module (local Qwen, JSON-only).

Turns free Italian text ("insalata con tonno 250g e pane") into a
structured meal. The LLM does the linguistic extraction; the service
layer (`cara.services.diet`) grounds the result against the DB catalog
(portions, status, protein category) and computes the deterministic
warnings — we never trust the 1.5B model with the rules.

If the LLM is unavailable or returns unparseable output, we fall back to
a lexical parser over the catalog so logging never hard-fails.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from cara.ai import get_llm_service
from cara.ai.llm import LLMUnavailableError

log = structlog.get_logger(__name__)

# Output cap is small — the schema is tiny. Keep it tight so the 1.5B
# doesn't ramble past the JSON.
_MAX_NEW_TOKENS = 320
_RKLLM_CONTEXT_TOKENS = 4092
_SAFETY = 64

SYSTEM_PROMPT = (
    "Sei un estrattore di dati alimentari. Ricevi la descrizione di un "
    "pasto in italiano e restituisci ESCLUSIVAMENTE un oggetto JSON valido, "
    "senza testo prima o dopo, senza spiegazioni, senza markdown.\n"
    "\n"
    "Schema ESATTO da rispettare:\n"
    "{\n"
    '  "items": [\n'
    '    {"food": "<nome alimento minuscolo>", "portion_g": <numero o null>, '
    '"protein_category": "<legumi|pesce|carne|uova|formaggio o null>", '
    '"status": "<consigliato|da_moderare|sconsigliato o null>"}\n'
    "  ],\n"
    '  "carb_present": <true|false>,\n'
    '  "vegetable_present": <true|false>,\n'
    '  "fruit_present": <true|false>,\n'
    '  "est_kcal": <numero intero o null>,\n'
    '  "warnings": ["<avviso breve in italiano>"]\n'
    "}\n"
    "\n"
    "Regole:\n"
    "- Estrai ogni alimento citato. Se il peso non è indicato, metti "
    "portion_g a null (lo completerà il sistema).\n"
    "- protein_category solo per la fonte proteica principale "
    "(legumi/pesce/carne/uova/formaggio); per pane, pasta, riso, verdura, "
    "frutta, olio usa null.\n"
    "- carb_present=true se c'è pasta, riso, pane, cereali o un primo piatto.\n"
    "- vegetable_present=true se c'è verdura/ortaggi/insalata.\n"
    "- fruit_present=true se c'è frutta.\n"
    "- est_kcal è una stima approssimativa e SECONDARIA; se non sai, null.\n"
    "- Non inventare alimenti non citati.\n"
    "Rispondi solo con il JSON."
)


def _render(system: str, user: str) -> str:
    envelope = (
        f"<|im_start|>system\n{system}<|im_end|>\n"
        f"<|im_start|>user\n<|im_end|>\n<|im_start|>assistant\n"
    )
    budget = _RKLLM_CONTEXT_TOKENS - _MAX_NEW_TOKENS - _SAFETY - len(envelope)
    if budget > 0 and len(user) > budget:
        user = user[:budget]
    return (
        f"<|im_start|>system\n{system}<|im_end|>\n"
        f"<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n"
    )


def _extract_json(text: str) -> dict[str, Any] | None:
    """Pull the first balanced JSON object out of the model output."""
    text = text.strip()
    # Strip code fences if the model wrapped them despite instructions.
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                blob = text[start : i + 1]
                try:
                    return json.loads(blob)
                except json.JSONDecodeError:
                    return None
    return None


def _normalise(raw: dict[str, Any]) -> dict[str, Any]:
    items = []
    for it in raw.get("items", []) or []:
        if not isinstance(it, dict):
            continue
        food = str(it.get("food", "")).strip().lower()
        if not food:
            continue
        portion = it.get("portion_g")
        try:
            portion = int(portion) if portion is not None else None
        except (TypeError, ValueError):
            portion = None
        pc = it.get("protein_category")
        if pc not in ("legumi", "pesce", "carne", "uova", "formaggio"):
            pc = None
        st = it.get("status")
        if st not in ("consigliato", "da_moderare", "sconsigliato"):
            st = None
        items.append(
            {"food": food, "portion_g": portion, "protein_category": pc, "status": st}
        )
    est = raw.get("est_kcal")
    try:
        est = int(est) if est is not None else None
    except (TypeError, ValueError):
        est = None
    warnings = [str(w) for w in (raw.get("warnings") or []) if str(w).strip()]
    return {
        "items": items,
        "carb_present": bool(raw.get("carb_present")),
        "vegetable_present": bool(raw.get("vegetable_present")),
        "fruit_present": bool(raw.get("fruit_present")),
        "est_kcal": est,
        "warnings": warnings,
    }


# ─── Lexical fallback ──────────────────────────────────────────────

_GRAM_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:g|gr|grammi)\b", re.IGNORECASE)
_VEG_HINTS = (
    "verdura", "insalata", "ortaggi", "zucchine", "peperoni", "spinaci",
    "zucca", "pomodor", "melanzane", "broccoli", "carot", "cipolla",
    "fagiolini", "finocchi", "cavolo", "minestrone", "passato", "vellutata",
)
_FRUIT_HINTS = (
    "frutta", "frutto", "mela", "pera", "banana", "arancia", "kiwi", "uva",
    "pesca", "fragole", "melone", "anguria", "cocomero", "mandarini",
)
_CARB_HINTS = (
    "pasta", "riso", "pane", "cereali", "farro", "orzo", "quinoa", "cous cous",
    "grano saraceno", "miglio", "gnocchi", "polenta", "fette biscottate",
    "primo", "panini", "crostini", "panificati",
)


def lexical_fallback(free_text: str, catalog_names: list[str]) -> dict[str, Any]:
    """Best-effort parse without the LLM: match catalog names + grams."""
    low = free_text.lower()
    # Grams with their position in the text, e.g. [(250, 9)].
    grams = [
        (int(float(m.group(1).replace(",", "."))), m.start())
        for m in _GRAM_RE.finditer(low)
    ]
    items: list[dict[str, Any]] = []
    # Longest names first so "salmone selvaggio" wins over "salmone".
    for name in sorted(catalog_names, key=len, reverse=True):
        if name in low and not any(name in i["food"] for i in items):
            items.append({
                "food": name,
                "portion_g": None,
                "protein_category": None,
                "status": None,
                "_pos": low.find(name),
            })
    # Order items by where they appear in the sentence (not by name length),
    # then attach each gram value to the food it textually follows.
    items.sort(key=lambda i: i["_pos"])
    for value, gpos in grams:
        # The food this gram belongs to = the last food starting before it,
        # else the first food (e.g. "250g di tonno").
        target = None
        for it in items:
            if it["_pos"] <= gpos:
                target = it
            else:
                break
        target = target or (items[0] if items else None)
        if target is not None and target["portion_g"] is None:
            target["portion_g"] = value
    for it in items:
        it.pop("_pos", None)
    return {
        "items": items,
        "carb_present": any(h in low for h in _CARB_HINTS),
        "vegetable_present": any(h in low for h in _VEG_HINTS),
        "fruit_present": any(h in low for h in _FRUIT_HINTS),
        "est_kcal": None,
        "warnings": [] if items else ["non ho riconosciuto alimenti nel testo"],
    }


async def parse_meal_text(free_text: str, catalog_names: list[str]) -> dict[str, Any]:
    """Parse a meal description → normalised dict (see SYSTEM_PROMPT schema).

    Tries the local LLM first; falls back to the lexical matcher on any
    failure so meal logging is always resilient.
    """
    try:
        llm = get_llm_service()
        prompt = _render(SYSTEM_PROMPT, free_text.strip())
        chunks: list[str] = []
        async for tok in llm.generate(prompt, max_new_tokens=_MAX_NEW_TOKENS, temperature=0.1):
            chunks.append(tok.text)
        raw = _extract_json("".join(chunks))
        if raw is not None:
            parsed = _normalise(raw)
            if parsed["items"]:
                return parsed
            log.info("diet.parse.llm_empty_items", text=free_text[:80])
    except LLMUnavailableError:
        log.info("diet.parse.llm_unavailable")
    except Exception as exc:  # noqa: BLE001
        log.warning("diet.parse.llm_failed", error=str(exc))
    return lexical_fallback(free_text, catalog_names)
