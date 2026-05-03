"""Deterministic intent router (Tier 1).

Run BEFORE the LLM is invoked. If the user query matches one of the
canonical command patterns below, we resolve the intent server-side
without ever generating tokens — saving 6-90 s of LLM latency and
sidestepping the 1.5B's tool-emission typos.

Pattern stolen from Lumo's two-tier router. Scope: only commands that
are unambiguous in Italian. Anything fuzzy falls through to the LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


@dataclass
class RoutedIntent:
    """Result of a successful router match."""

    kind: str              # "play_radio" | "list_tasks" | "discover_article" | …
    args: dict[str, str]   # e.g. {"query": "rai radio 1"}
    confidence: float      # 1.0 = exact match
    canned_reply: str      # short prose to play back to the user


# Stop-list of nouns that, when present in a query, BLOCK a generic
# "metti X" / "accendi X" match — they signal smart-home or housekeeping
# requests that have no business being routed as radio playback.
# Anchored at \b so we don't trip on substrings.
_SMART_HOME_STOPWORDS = re.compile(
    r"\b(?:luce|luci|lampad[ae]|finestr[ae]|port[ae]|"
    r"riscaldamento|termosifon[ei]|condizionatore|aria\s+condizionata|"
    r"allarme|antifurto|"
    r"cucina|salotto|camera|bagno|garage|giardino|cortile|"
    r"forno|frigo|frigorifero|lavatrice|lavastoviglie|"
    r"a\s+posto|in\s+ordine)\b",
    re.IGNORECASE,
)

# Audio-domain *content nouns* that confirm a "metti X" / "accendi X"
# really is a media playback request. These are nouns only — verbs like
# "ascoltare/sentire" appear in the trigger phrases themselves
# ("fammi sentire bene") and would cause false matches if added.
_AUDIO_DOMAIN = re.compile(
    r"\b(?:radio|stazione|musica|canzone|canzoni|album|playlist|podcast|"
    r"puntata|brano|disco)\b",
    re.IGNORECASE,
)


# (regex_pattern, intent_kind, canned_reply, arg_extractor)
# Patterns are ITALIAN only. Anchored at ^ and \s*[?!.]*$ so trailing
# punctuation doesn't break matching. Order matters: more specific first.
_RULES: list[tuple[re.Pattern[str], str, str, Callable[[re.Match[str]], dict[str, str]]]] = [
    # ---- Audio / radio ----------------------------------------------------
    (
        re.compile(
            r"^(?:fammi\s+(?:ascoltare|sentire)|metti(?:mi)?|accendi|riproduc[ei])\s+"
            r"(?:la\s+)?(?:radio\s+)?(?P<q>.+?)\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "discover_audio",
        "La metto su.",
        lambda m: {"query": m.group("q").strip(), "kind": "audio_stream"},
    ),
    # ---- News -------------------------------------------------------------
    (
        re.compile(
            r"^(?:dimmi(?:le)?|leggimi|che\s+sono)?\s*"
            r"(?:le\s+)?(?:ultime\s+)?notiz(?:ie|ia)"
            r"(?:\s+(?:di|del|sul|in)\s+(?P<cat>italia|mondo|economia|tech|tecnologia|sport))?"
            r"\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "get_news",
        "Ecco le ultime notizie.",
        lambda m: {
            "category": (
                "tech" if (m.group("cat") or "").lower() == "tecnologia"
                else (m.group("cat") or "all").lower()
            ),
        },
    ),
    # ---- Tasks list -------------------------------------------------------
    (
        re.compile(
            r"^(?:cosa\s+devo\s+fare|mostra(?:mi)?\s+(?:la\s+)?lista|"
            r"che\s+cose\s+devo\s+fare|le\s+mie\s+task|"
            r"(?:fammi\s+)?vedere\s+la\s+lista)\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "list_tasks",
        "Ecco la tua lista.",
        lambda m: {},
    ),
    # ---- Add task ---------------------------------------------------------
    # IMPORTANT: this pattern is greedy on the title — if the user said
    # "aggiungi X alla spesa" the shopping rule below takes precedence
    # because it's more specific (so we list shopping first in the file).
    (
        re.compile(
            r"^(?:ricordami|aggiungi(?:\s+alla\s+(?:mia\s+)?lista)?|"
            r"devo|mi\s+serve|metti\s+in\s+lista)\s+(?:di\s+)?(?P<title>.+?)\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "add_task",
        "Aggiunto.",
        lambda m: {"title": m.group("title").strip()},
    ),
    # ---- Add shopping (must be checked BEFORE add_task) -------------------
    # We solve the precedence by re-checking after add_task fires — see
    # match() below.
    (
        re.compile(
            r"^(?:aggiungi|metti|compra)\s+(?P<title>.+?)\s+"
            r"(?:alla\s+(?:lista\s+della\s+)?spesa)\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "add_shopping",
        "Messo nella spesa.",
        lambda m: {"title": m.group("title").strip()},
    ),
    # ---- Who is home ------------------------------------------------------
    (
        re.compile(
            r"^chi\s+(?:c'?\s*è|sta|è)\s+"
            r"(?:in\s+casa(?:\s+(?:adesso|ora|in\s+questo\s+momento))?"
            r"|adesso\s+in\s+casa"
            r"|a\s+casa)"
            r"\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "who_is_home",
        "Guardo subito.",
        lambda m: {},
    ),
    # ---- Date / time / month / year — answered from runtime context -------
    (
        re.compile(
            r"^(?:che\s+(?:giorno|data|ora|mese|anno)\s+(?:è|siamo)(?:\s+oggi)?|"
            r"che\s+ore\s+sono|"
            r"in\s+che\s+(?:mese|anno)\s+siamo|"
            r"dimmi\s+(?:la\s+)?(?:data|l'ora|che\s+giorno\s+è)|"
            r"oggi\s+che\s+(?:giorno|data)\s+è)\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "answer_datetime",
        "",  # the chat layer fills this from the runtime context
        lambda m: {},
    ),
    # ---- Definition / what-is — route to article discovery (CDA fast path)
    (
        re.compile(
            r"^(?:cos['e]?\s*(?:è|e)|chi\s+(?:è|sono)|spiegami|definisci|"
            r"dimmi\s+cos[ae]\s+(?:significa|vuol\s+dire))\s+(?P<q>.+?)\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "discover_article",
        "Cerco e ti dico.",
        lambda m: {"query": m.group("q").strip(), "kind": "article"},
    ),
]


def _validate_routed(routed: RoutedIntent, query: str) -> RoutedIntent | None:
    """Post-match sanity check. Reject the routed intent when its argument
    is clearly out of domain — typically a "metti X" where X mentions
    smart-home items (luce, cucina, …) instead of audio content.

    Returns the intent unchanged when valid, None otherwise (the caller
    treats None as "fall through to the LLM").
    """
    if routed.kind == "discover_audio":
        target = routed.args.get("query", "").strip()
        # Hard block: anything mentioning a smart-home stopword.
        if _SMART_HOME_STOPWORDS.search(target):
            return None
        # Soft requirement: when the query was ambiguous ("metti X"), we
        # need at least one audio-domain keyword in the FULL query OR a
        # plausible station-shaped target (≥2 chars, mostly letters).
        # If neither is true, fall through to the LLM.
        if not _AUDIO_DOMAIN.search(query):
            # No content noun like "radio/musica/podcast/...". Without
            # that signal we can't reliably tell "metti capital" from
            # "metti via tutto" — fall through to the LLM, which sees
            # the discover examples in its system prompt and can disambiguate.
            return None
    return routed


def match(query: str) -> RoutedIntent | None:
    """Try each rule in order; return the first that matches.

    The shopping rule is intentionally placed AFTER `add_task` in the list
    above for readability, but takes precedence here: we run the shopping
    pattern as a tie-breaker first so that "aggiungi X alla spesa" doesn't
    end up in the tasks list.
    """
    if not query:
        return None
    q = query.strip()
    if not q or len(q) > 200:
        return None

    # Run the shopping-specific check BEFORE the generic add_task rule.
    for rx, kind, canned, extract in _RULES:
        if kind == "add_shopping":
            m = rx.match(q)
            if m:
                return _validate_routed(
                    RoutedIntent(kind=kind, args=extract(m), confidence=1.0, canned_reply=canned),
                    q,
                )
            break

    # Standard pass.
    for rx, kind, canned, extract in _RULES:
        if kind == "add_shopping":
            continue   # already tried above
        m = rx.match(q)
        if m:
            validated = _validate_routed(
                RoutedIntent(kind=kind, args=extract(m), confidence=1.0, canned_reply=canned),
                q,
            )
            if validated is not None:
                return validated
            # validation rejected — keep trying the remaining rules.
    return None
