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
            r"^(?:cara,?\s*)?"
            r"(?:dim[mn]i(?:le)?|dam[mn]i|leggi(?:mi|ci|tele)?|"
            r"mostra(?:mi|ci)?|fammi\s+vedere|elenca(?:mi)?|"
            r"che\s+(?:cosa\s+)?(?:c['’]?\s*[èe]|sono|ci\s+sono)|"
            r"quali\s+sono|che\s+novit[àa])?\s*"
            r"(?:le\s+|alcune\s+|qualche\s+)?(?:ultime\s+)?notiz(?:ie|ia)"
            r"(?:\s+(?:di|del|sul|in|sulla|sull['’]|su|riguard[oa])\s+"
            r"(?P<cat>italia|mondo|economia|tech|tecnologia|sport|cronaca|esteri))?"
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
    # ---- Weather ----------------------------------------------------------
    # Forecast intent backed by `cara.services.weather.WeatherService`
    # (Open-Meteo). Scope = today / tomorrow / week.
    (
        re.compile(
            r"^(?:cara,?\s*)?"
            r"(?:che\s+tempo\s+(?:fa|farà|c['’]?\s*[èe])|"
            r"come\s+(?:è\s+il\s+|sarà\s+il\s+)?tempo|"
            r"come\s+(?:sarà|è)\s+il\s+meteo|"
            r"(?:dim[mn]i(?:mi)?|dam[mn]i|fammi\s+vedere|mostra(?:mi)?|leggi(?:mi)?)\s+"
            r"(?:il\s+|le\s+)?(?:meteo|previsioni|tempo)|"
            r"(?:il\s+)?meteo|(?:le\s+)?previsioni(?:\s+meteo)?|"
            r"(?:fa|farà)\s+(?:caldo|freddo|brutto|bello))"
            r"(?:\s+(?:(?:di|per|a)\s+)?(?:oggi|domani|questa\s+settimana|"
            r"(?:la\s+)?(?:prossima\s+settimana|settimana\s+prossima)|stasera))?"
            r"(?:\s+(?:a|in|su)\s+(?P<city>[\w\s'à-úÀ-Ú-]{2,40}))?"
            r"\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "answer_weather",
        "Controllo il meteo.",
        lambda m: {
            "scope": (
                "tomorrow" if "domani" in m.group(0).lower()
                else "week" if "settimana" in m.group(0).lower()
                else "today"
            ),
            "city": (m.group("city") or "").strip() or None,
        },
    ),
    # ---- Capabilities — "cosa puoi fare", "chi sei", "aiuto" --------------
    # CARA must NEVER answer "non so", "non posso" to its own capabilities.
    # This rule fires first so a misroute by the LLM is impossible.
    (
        re.compile(
            r"^(?:cara,?\s*)?"
            r"(?:cosa\s+(?:sai|puoi)\s+fare|"
            r"a\s+cosa\s+servi|"
            r"come\s+(?:funzioni|posso\s+usarti)|"
            r"(?:dim[mn]i|spiegami)\s+cosa\s+(?:sai|puoi)\s+fare|"
            r"aiuto|help|"
            r"quali\s+sono\s+le\s+tue\s+(?:funzioni|funzionalit[àa])|"
            r"funzionalit[àa])\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "capabilities",
        "",  # filled by resolver from a static block
        lambda m: {},
    ),
    # ---- Identity ---------------------------------------------------------
    (
        re.compile(
            r"^(?:cara,?\s*)?"
            r"(?:chi\s+sei|come\s+ti\s+chiami|presentati|"
            r"qual\s+[èe]\s+il\s+tuo\s+nome)\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "identity",
        "",
        lambda m: {},
    ),
    # ---- Appointments — tasks WITH due_date only --------------------------
    # The user thinks of "appuntamenti" as the subset of tasks that have a
    # due date. Cheap to satisfy: filter on the way out.
    #
    # The pattern is union-based: each `_APPT_*` alternative is a separate
    # natural phrasing the family uses. Keep it permissive — false positives
    # here just produce "Non hai appuntamenti", false negatives produce
    # LLM hallucinations or get swallowed by the skill dispatcher.
    (
        re.compile(
            # 1. Imperative list verb: "elencami / dammi / dimmi / mostrami /
            #    leggimi / fammi vedere / quali sono [i miei] [appuntamenti]
            #    [di oggi / di domani / di questa settimana / della prossima
            #    settimana / della settimana prossima]?"
            r"^(?:cara,?\s*)?"
            r"(?:elenca(?:mi)?|mostra(?:mi)?|dim[mn]i|dam[mn]i|"
            r"fammi\s+vedere|leggi(?:mi)?|quali\s+sono|"
            r"vediamo|hai)\s+"
            r"(?:tutti\s+(?:gli\s+|i\s+)?|i\s+|gli\s+|qualche\s+|gli\s+eventuali\s+)?"
            r"(?:miei\s+|tuoi\s+)?"
            r"(?:appuntament(?:i|o)|impegni|impegno|event(?:i|o))"
            r"(?:\s+(?:di|per|della|nella|in)\s+(?:oggi|domani|questa\s+settimana|"
            r"(?:la\s+)?(?:prossima\s+settimana|settimana\s+prossima)|"
            r"questo\s+weekend|il\s+weekend|stasera))?"
            r"\s*[?!.]*$|"

            # 2. Bare noun: "appuntamenti?" "i miei impegni" "appuntamenti
            #    della settimana prossima" "impegni di oggi" "appuntamenti
            #    del weekend" "appuntamenti settimana prossima" (no prep)
            r"^(?:i\s+miei\s+|gli\s+|tutti\s+gli\s+|miei\s+)?"
            r"(?:appuntament(?:i|o)|impegni|impegno)"
            r"(?:\s+(?:(?:di|della|del|dell['’]|in|per)\s+)?"
            r"(?:oggi|domani|questa\s+settimana|"
            r"(?:la\s+)?(?:prossima\s+settimana|settimana\s+prossima)|"
            r"weekend|questo\s+weekend|il\s+weekend|fine\s+settimana|"
            r"stasera))?"
            r"\s*[?!.]*$|"

            # 3. Question form with "che/quali/quanti": "che appuntamenti
            #    ho oggi?" "quali impegni ho domani?" "quanti appuntamenti
            #    ho questa settimana?"
            r"^(?:cara,?\s*)?"
            r"(?:che|quali|quanti)\s+"
            r"(?:appuntament(?:i|o)|impegni|impegno|event(?:i|o))\s+"
            r"(?:ho|abbiamo|c['’]\s*sono)"
            r"(?:\s+(?:oggi|domani|questa\s+settimana|"
            r"(?:la\s+)?(?:prossima\s+settimana|settimana\s+prossima)|"
            r"in\s+programma|stasera|questo\s+weekend))?"
            r"\s*[?!.]*$|"

            # 4. Plain "ho appuntamenti?" / "ho impegni oggi?"
            r"^(?:ho|abbiamo)\s+"
            r"(?:appuntament(?:i|o)|impegni|impegno)"
            r"(?:\s+(?:oggi|domani|questa\s+settimana|"
            r"(?:la\s+)?(?:prossima\s+settimana|settimana\s+prossima)|"
            r"in\s+programma|stasera|questo\s+weekend))?"
            r"\s*[?!.]*$|"

            # 5. "cosa ho / che ho / che cosa ho" + scope token (kept for
            #    backward compat with previous regex shape)
            r"^(?:cosa\s+ho|che\s+(?:cosa\s+)?ho)\s+"
            r"(?:in\s+programma|da\s+fare\s+(?:oggi|domani|questa\s+settimana|"
            r"(?:la\s+)?(?:prossima\s+settimana|settimana\s+prossima)))"
            r"\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "list_appointments",
        "Ecco gli appuntamenti.",
        lambda m: {"scope": _appt_scope(m.group(0).lower())},
    ),
    # ---- Tasks list, today only -------------------------------------------
    # Must come BEFORE the generic list_tasks rule so "oggi" wins.
    (
        re.compile(
            r"^(?:cosa\s+devo\s+fare\s+oggi|"
            r"(?:mostra(?:mi)?|dim[mn]i|fammi\s+vedere)\s+"
            r"(?:i\s+|le\s+|la\s+lista\s+(?:de(?:i|lle)\s+)?)?(?:task|attivit[àa]|cose)\s+(?:di\s+)?oggi|"
            r"(?:i\s+|le\s+)?(?:miei\s+)?(?:task|attivit[àa]|cose)\s+(?:di\s+)?oggi|"
            r"quali\s+(?:sono\s+(?:i|le)\s+)?(?:miei\s+)?(?:task|attivit[àa])\s+(?:di\s+)?oggi)"
            r"\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "list_tasks_today",
        "Ecco le cose di oggi.",
        lambda m: {},
    ),
    # ---- Tasks list (all) -------------------------------------------------
    (
        re.compile(
            r"^(?:cara,?\s*)?"
            r"(?:cosa\s+devo\s+fare|"
            r"(?:mostra(?:mi)?|dim[mn]i|dam[mn]i|fammi\s+vedere|elenca(?:mi)?|leggi(?:mi)?)\s+"
            r"(?:tutt[ei]\s+)?"
            r"(?:la\s+(?:mia\s+)?lista(?:\s+(?:de(?:i|lle|gli)\s+)?(?:task|attivit[àa]|cose|cose\s+da\s+fare))?|"
            r"(?:i\s+|le\s+)?(?:miei\s+|mie\s+)?(?:task|attivit[àa]|cose\s+da\s+fare))|"
            # Bare nouns: "lista delle cose da fare", "le cose da fare", "le mie task"
            r"(?:la\s+)?(?:mia\s+)?lista(?:\s+(?:de(?:i|lle|gli)\s+)?(?:task|attivit[àa]|cose(?:\s+da\s+fare)?))?|"
            r"(?:le\s+|i\s+)?(?:mie\s+|miei\s+)?cose\s+da\s+fare|"
            r"che\s+cose\s+devo\s+fare|"
            r"(?:i\s+|le\s+)?(?:miei\s+|mie\s+)?(?:task|attivit[àa])\s+totali|"
            r"(?:fammi\s+)?vedere\s+(?:la\s+)?(?:mia\s+)?lista|"
            r"(?:i\s+|le\s+)(?:miei\s+|mie\s+)(?:task|attivit[àa]|cose\s+da\s+fare)|"
            r"quali\s+(?:sono\s+(?:i|le)\s+)?(?:miei\s+|mie\s+)?(?:task|attivit[àa]|cose\s+da\s+fare))"
            r"\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "list_tasks",
        "Ecco la tua lista.",
        lambda m: {},
    ),
    # ---- Shopping list (read) --------------------------------------------
    (
        re.compile(
            r"^(?:cara,?\s*)?"
            r"(?:cosa\s+devo\s+comprare|"
            r"(?:mostra(?:mi)?|dim[mn]i|dam[mn]i|fammi\s+vedere|elenca(?:mi)?|leggi(?:mi)?)\s+"
            r"(?:la\s+)?(?:mia\s+)?(?:lista\s+(?:della\s+)?)?spesa|"
            r"(?:la\s+)?(?:mia\s+)?lista\s+(?:della\s+)?spesa|"
            # Bare "la spesa" / "spesa" — most common phrasing.
            r"(?:la\s+)?spesa|"
            r"(?:cosa|che\s+cosa)\s+(?:c['e]?\s*[èe]|ho|abbiamo)\s+"
            r"(?:nella\s+|sulla\s+)?(?:lista\s+(?:della\s+)?)?spesa|"
            r"(?:la\s+)?spesa\s+da\s+fare|"
            r"quali\s+(?:sono\s+)?(?:gli\s+articoli\s+)?(?:nella\s+|della\s+)?(?:lista\s+)?spesa)"
            r"\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "list_shopping",
        "Ecco la spesa.",
        lambda m: {},
    ),
    # ---- Notes list ------------------------------------------------------
    (
        re.compile(
            r"^(?:cara,?\s*)?"
            r"(?:(?:mostra(?:mi)?|dim[mn]i|dam[mn]i|fammi\s+vedere|elenca(?:mi)?|leggi(?:mi)?)\s+"
            r"(?:le\s+|tutte\s+le\s+)?(?:mie\s+)?note|"
            r"(?:le\s+|tutte\s+le\s+)?(?:mie\s+)?note|"
            r"quali\s+(?:sono\s+(?:le\s+)?)?(?:mie\s+)?note)"
            r"\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "list_notes",
        "Ecco le tue note.",
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
    # ---- Mark shopping bought (BEFORE delete_task — "ho comprato X" matches first) ----
    (
        re.compile(
            r"^(?:cara,?\s*)?"
            r"(?:ho\s+(?:gi[àa]\s+)?(?:comprato|preso)|"
            r"comprato|preso|gi[àa]\s+preso)\s+(?P<title>.+?)\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "mark_shopping_bought",
        "Segnato come preso.",
        lambda m: {"title": m.group("title").strip()},
    ),
    # ---- Delete shopping (BEFORE delete_task — "X dalla spesa" wins) -----
    (
        re.compile(
            r"^(?:cara,?\s*)?"
            r"(?:cancella(?:mi)?|elimina(?:mi)?|rimuovi(?:mi)?|togli(?:mi)?)\s+"
            r"(?P<title>.+?)\s+"
            r"(?:dalla\s+(?:lista\s+(?:della\s+)?)?spesa)\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "delete_shopping",
        "Tolto dalla spesa.",
        lambda m: {"title": m.group("title").strip()},
    ),
    # ---- Complete a task by title (mark done) -----------------------------
    (
        re.compile(
            r"^(?:cara,?\s*)?"
            r"(?:ho\s+(?:fatto|finito|completato)|fatto|completata?)\s+(?P<title>.+?)\s*[?!.]*$|"
            r"^(?:segna\s+come\s+(?:fatta?|completata?)|completa)\s+(?P<title2>.+?)\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "complete_task",
        "Fatto.",
        lambda m: {"title": (m.group("title") or m.group("title2") or "").strip()},
    ),
    # ---- Delete note (BEFORE delete_task — "nota X" wins) ---------------
    (
        re.compile(
            r"^(?:cara,?\s*)?"
            r"(?:cancella(?:mi)?|elimina(?:mi)?|rimuovi(?:mi)?)\s+"
            r"(?:la\s+)?nota\s+(?P<title>.+?)\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "delete_note",
        "Nota eliminata.",
        lambda m: {"title": m.group("title").strip()},
    ),
    # ---- Delete task by title --------------------------------------------
    (
        re.compile(
            r"^(?:cara,?\s*)?"
            r"(?:cancella(?:mi)?|elimina(?:mi)?|rimuovi(?:mi)?|togli(?:mi)?|annulla)\s+"
            r"(?:la\s+task|l['\s]?attivit[àa])?\s*"
            r"(?P<title>.+?)\s*"
            r"(?:dalla\s+(?:mia\s+)?lista(?:\s+(?:dei|delle)\s+(?:task|attivit[àa]|cose))?)?"
            r"\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "delete_task",
        "Eliminata.",
        lambda m: {"title": m.group("title").strip()},
    ),
    # ---- Duplicate a task ------------------------------------------------
    (
        re.compile(
            r"^(?:duplica(?:mi)?|copia(?:mi)?)\s+(?:la\s+task\s+|l['\s]?attivit[àa]\s+)?(?P<title>.+?)\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "duplicate_task",
        "Duplicata.",
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
    # ---- Notes: add (delete moved up before delete_task) -----------------
    # Body separator can be whitespace, ":", or "," — typical typed input
    # uses "salvami una nota: chiamare lo zio" with the colon.
    (
        re.compile(
            r"^(?:cara,?\s*)?"
            r"(?:salva(?:mi)?\s+(?:una\s+)?nota|scrivi(?:mi)?\s+(?:una\s+)?nota|"
            r"prendi(?:mi)?\s+(?:una\s+)?nota|appunta(?:mi)?|nota:?)"
            r"(?:\s*[:,]\s*|\s+(?:che|di)\s+|\s+)(?P<body>.+?)\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "add_note",
        "Nota salvata.",
        lambda m: {"body": m.group("body").strip()},
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
    # ---- Sleep / wake — LUMO-style FSM transitions (no LLM, no hardware) --
    # Transitions the global StateMachine into sleeping/idle so frontend
    # bridges (Edo expression, halo color) update without a chat round-trip.
    (
        re.compile(
            r"^(?:cara,?\s*)?(?:buona\s*notte|buonanotte|"
            r"vai\s+a\s+dormire|dormi|riposa(?:ti)?|"
            r"a\s+dopo|spegniti)\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "go_sleep",
        "Buonanotte.",
        lambda m: {},
    ),
    (
        re.compile(
            r"^(?:cara,?\s*)?(?:sveglia(?:ti)?|"
            r"buon\s*giorno|buongiorno|"
            r"ciao\s+cara|ehi\s+cara|alzati)\s*[?!.]*$",
            re.IGNORECASE,
        ),
        "wake_up",
        "Eccomi.",
        lambda m: {},
    ),
]


def _appt_scope(q: str) -> str:
    """Pick "today" / "tomorrow" / "week" / "next_week" / "weekend" / "all"
    from the user phrasing. Order matters: more specific tokens win."""
    q = q.lower()
    if "domani" in q:
        return "tomorrow"
    if "prossima settimana" in q or "settimana prossima" in q:
        return "next_week"
    if "weekend" in q or "fine settimana" in q:
        return "weekend"
    if "settimana" in q:
        return "week"
    if "stasera" in q:
        return "tonight"
    if "oggi" in q or "in programma" in q:
        return "today"
    return "all"


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
