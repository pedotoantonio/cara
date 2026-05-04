"""Server-side mini-agent: 'aggiungi gli ingredienti della ricetta X alla spesa'.

This bypasses the LLM tool-calling round-trip entirely for one specific high-
value pattern that the 1.5B model can't handle reliably (it tends to take the
word 'ingredienti' literally and add it as a single shopping item).

Flow:
1. `detect_intent(message)` returns the dish name if the message matches the
   pattern, else None.
2. `run(session, user_id, dish)` does:
   - call CDA `discover(query="ricetta X ingredienti", kind="article")`
   - extract ingredients from the article text via deterministic heuristics
     (the "Ingredienti" section header is a near-universal Italian recipe
     convention — no LLM call needed for parsing)
   - persist each via `shopping_svc.create_item`
   - return a human-readable summary string for streaming back to the user

Heuristic, not perfect: failure modes (no recipe found, no Ingredienti
section, OCR'd page) all return a graceful fallback message.
"""

from __future__ import annotations

import re
from typing import Iterable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cara.cda import CdaError, DiscoverRequest, discover as cda_discover
from cara.services import shopping as shopping_svc

log = structlog.get_logger(__name__)


# ---- intent detection -------------------------------------------------------

# Captures: "aggiungi/metti/aggiungimi gli ingredienti (di|della|del|per) X
# alla (lista della) spesa". The dish X stops at common boundary words.
_INTENT_RE = re.compile(
    r"\b(?:aggiun\w+|mett\w+|metti\w*|inserisc\w+)\b"
    r".{0,30}?\bingredient\w+\b"
    r".{0,15}?(?:per|della|delle|dello|degli|dell[ie]|dei|del|di|de|d['’])\s+"
    r"(?:la|il|lo|le|i|gli|l['’]|fare\s+(?:la|il|lo|le|i|gli|l['’])?)?\s*"
    r"(?P<dish>[\w'’àèéìòù\s\-]{3,80}?)"
    r"(?:\s+(?:alla|nella|in|sulla|sul)\s+(?:lista\s+(?:della\s+)?)?spesa\b|$)",
    flags=re.IGNORECASE,
)


def detect_intent(message: str) -> str | None:
    """Return the dish name if the message asks to add recipe ingredients to
    the shopping list. None otherwise."""
    m = _INTENT_RE.search(message or "")
    if not m:
        return None
    dish = (m.group("dish") or "").strip(" .,;:")
    if not dish or len(dish) < 3:
        return None
    return dish


# ---- ingredient extraction --------------------------------------------------

# Match the "Ingredienti" header ONLY when followed by a newline that begins
# a list line (bullet or number). Skips inline mentions like
# "...basato sugli ingredienti e sul metodo di preparazione...".
_HEADER_RE = re.compile(
    r"\bingredienti\b[ \t:]*\n(?=[-•·*\d])",
    flags=re.IGNORECASE,
)
# End-of-section markers used in italian recipes.
_END_SECTION_RE = re.compile(
    r"\b(preparazione|procedimento|esecuzione|note|consigli|varianti|"
    r"conservazione|preparation|method|instructions|"
    r"come\s+(?:preparare|fare|cucinare|cuocere|si\s+prepar\w+))\b",
    flags=re.IGNORECASE,
)
# Quantity at LINE START — "300 g di farina", "1 bustina di sale", "q.b. di olio".
_QTY_PREFIX_RE = re.compile(
    r"^\s*(?:[\d,./×x]+\s*)?"
    r"(?:g|gr|grammi|kg|ml|cl|l|cc|cucchiai\w*|cucchiaini\w*|"
    r"tazze?|pizzichi?|bustine?|cubetti?|spicchi?|fogli?|fette?|"
    r"pizzic\w+|q\.?\s*b\.?|pari\s+peso)\s+(?:di|d['’])?\s+",
    flags=re.IGNORECASE,
)
# Quantity at LINE END — "Farina 00 90 g", "Uova 4", "Zucchero a velo q.b."
# (GialloZafferano-style format). Strip everything from the first trailing
# number/unit to end of line.
_QTY_SUFFIX_RE = re.compile(
    r"\s+(?:[\d,./×x]+(?:\s*(?:g|gr|grammi|kg|ml|cl|l|cc|cm|mm|"
    r"cucchiai\w*|cucchiaini\w*|tazze?|pizzichi?|bustine?|cubetti?|"
    r"spicchi?|fogli?|fette?))?|q\.?\s*b\.?)\s*\.?$",
    flags=re.IGNORECASE,
)
_BAD_LINE = re.compile(r"^\s*(•|-|\*|·|\d+[.)])\s*")
_PARENS = re.compile(r"\s*\([^)]*\)")
_TRAILING_NOTE = re.compile(r"\s*[—–-]\s.*$")
# Lines that are sub-headers ("per decorare", "per la base", "Ingredienti
# per...") and not actual ingredients.
_SUBHEADER_RE = re.compile(
    r"^(?:ingredienti\b|per\s+(?:decorare|la|il|lo|le|i|gli|un[oa]?)\b|"
    r"facoltativ\w*)",
    flags=re.IGNORECASE,
)


def _clean_line(raw: str) -> str | None:
    s = raw.strip()
    if not s:
        return None
    s = _BAD_LINE.sub("", s)
    s = _PARENS.sub("", s)
    s = _TRAILING_NOTE.sub("", s)
    # Strip quantity at either end (we don't know which format the page uses).
    s = _QTY_PREFIX_RE.sub("", s)
    s = _QTY_SUFFIX_RE.sub("", s).strip()
    if not s:
        return None
    if _SUBHEADER_RE.match(s):
        return None
    if len(s) > 50 or len(s) < 2:
        return None
    if any(c in s for c in ".:"):
        return None
    # Reject obvious non-ingredients (numbers only, dots, etc.)
    if not re.search(r"[a-zàèéìòù]{2,}", s, flags=re.IGNORECASE):
        return None
    return " ".join(s.lower().split())


def extract_ingredients(text: str, *, max_items: int = 30) -> list[str]:
    """Pull a list of ingredient names from a recipe article body.

    Looks for the 'Ingredienti' section header, takes the lines until the next
    section heading (Preparazione/Procedimento/...) or after `max_items`.
    Returns deduplicated, lowercased noun phrases (best-effort)."""
    if not text:
        return []
    m = _HEADER_RE.search(text)
    if m is None:
        return []
    chunk = text[m.end() :]
    # Stop at the next section heading
    end = _END_SECTION_RE.search(chunk)
    if end is not None:
        chunk = chunk[: end.start()]
    # Lines may be separated by newlines OR by " · " / commas in some HTML→text
    # extractions. We split on newlines first; if we got nothing useful, try
    # splitting on bullet/comma.
    raw_lines: Iterable[str] = chunk.splitlines()
    cleaned: list[str] = []
    seen: set[str] = set()
    for line in raw_lines:
        c = _clean_line(line)
        if c and c not in seen:
            seen.add(c)
            cleaned.append(c)
        if len(cleaned) >= max_items:
            break
    if len(cleaned) >= 3:
        return cleaned
    # Fallback: split on commas/bullets in case the page rendered the list
    # inline ("300 g di farina, 200 g di zucchero, 4 uova, ...").
    parts = re.split(r"[,;·•]", chunk[:1500])
    cleaned = []
    seen = set()
    for p in parts:
        c = _clean_line(p)
        if c and c not in seen:
            seen.add(c)
            cleaned.append(c)
        if len(cleaned) >= max_items:
            break
    return cleaned


# ---- chain ------------------------------------------------------------------


async def run(
    session: AsyncSession,
    *,
    user_id: int,
    dish: str,
) -> str:
    """Discover the recipe, extract ingredients, add to shopping. Returns a
    human-readable summary suitable for streaming back to the user."""
    log.info("recipe_chain.start", dish=dish, user_id=user_id)
    query = f"ricetta {dish} ingredienti"
    try:
        result = await cda_discover(
            session,
            DiscoverRequest(
                user_id=user_id, raw_query=query, content_type="article", modifiers={}
            ),
        )
    except CdaError as exc:
        return (
            f"Non sono riuscita a trovare una ricetta per «{dish}» su internet "
            f"({exc}). Prova a darmi tu gli ingredienti."
        )
    text = str(result.metadata.get("text") or "")
    ingredients = extract_ingredients(text)
    if not ingredients:
        return (
            f"Ho trovato la ricetta di {dish} ({result.source_domain or 'sito web'}), "
            f"ma non sono riuscita a estrarne la lista degli ingredienti in modo "
            f"affidabile. Aprila tu se vuoi: {result.url}"
        )
    added: list[str] = []
    for ing in ingredients:
        try:
            await shopping_svc.create_item(session, user_id=user_id, title=ing)
            added.append(ing)
        except Exception as exc:  # noqa: BLE001
            log.warning("recipe_chain.add_failed", ingredient=ing, error=str(exc))
    src = f" (fonte: {result.source_domain})" if result.source_domain else ""
    listed = ", ".join(added[:8])
    extra = f" e altri {len(added) - 8}" if len(added) > 8 else ""
    return (
        f"Ho cercato la ricetta di {dish}{src} e ho aggiunto {len(added)} "
        f"ingredienti alla lista della spesa: {listed}{extra}."
    )
