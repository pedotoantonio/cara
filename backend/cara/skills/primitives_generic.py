"""Generic skill primitives — Phase B of Skill Factory.

These primitives are domain-agnostic: any skill author can compose them.

  - **extract_list** — pull a list of items from free text (bullet
    markers, numbered lists, or a labelled section). The bread-and-butter
    of "ricetta → ingredienti", "menu → portate", "elenco compiti", etc.

  - **summarize** — extractive summary using the project's
    existing TF-IDF / Jaccard ranker (no LLM, deterministic).

  - **ask_user** — surface a clarification prompt back to the user. The
    primitive returns a marker dict; the skill's response_template
    interpolates `{step.prompt}` so the user sees the question and the
    flow stops there. Useful for slot disambiguation.

  - **read_url** — fetch an HTTP(S) URL and return cleaned main text
    (trafilatura when available, regex fallback otherwise). Capped at
    `max_chars` to keep prompts manageable.

Importing this module registers all four primitives via the @primitive
decorator. cara/skills/primitives.py imports it at module load.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

from cara.services.extractive_summary import extract_top_sentences
from cara.skills.registry import primitive

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 1) extract_list — generic list extraction
# ---------------------------------------------------------------------------

# Markers that introduce a bullet/numbered item at line start.
# - Bullets: `-`, `*`, `•`, `‣`, `▪`, `→`
# - Numeric: `1.`, `1)`, `(1)`, `01.`, etc.
_BULLET_RE = re.compile(
    r"""^\s*
        (?:
            [-*•‣▪→]            # plain bullet
            |\d+[.)]            # 1. or 1)
            |\(\d+\)            # (1)
        )
        \s+
    """,
    re.VERBOSE,
)

# Italian section headers we use as anchors when `hint` is empty:
# "Ingredienti:", "Lista:", "Elenco:", "Cose da fare:" etc.
_DEFAULT_HEADER_HINTS = (
    "ingredienti", "lista", "elenco", "cose da fare", "to do",
    "menu", "portate", "compiti",
)


def _find_section(text: str, hint: str) -> str:
    """If `hint` (or a default header) appears in `text`, return the slice
    starting after the header line. Otherwise return the original text."""
    needle = (hint or "").strip().lower()
    candidates = (needle,) if needle else _DEFAULT_HEADER_HINTS
    lower = text.lower()
    best: int = -1
    for c in candidates:
        if not c:
            continue
        # Match `<hint>:` or `<hint>\n`
        for pat in (f"{c}:", f"{c}\n", f"{c} \n"):
            i = lower.find(pat)
            if i != -1 and (best == -1 or i < best):
                best = i + len(pat)
                break
    if best == -1:
        return text
    return text[best:]


@primitive(
    name="extract_list",
    description=(
        "Estrae un elenco di voci da un testo libero. Riconosce trattini "
        "(- * •), elenchi numerati (1. 1) (1)) e una sezione con etichetta "
        "esplicita ('Lista:', 'Elenco:', 'Ingredienti:'). Argomento `hint` "
        "opzionale per restringere la ricerca alla sezione richiesta."
    ),
    args_schema={"text": "string", "hint": "string", "max_items": "int"},
    returns_schema={"items": "list[str]", "count": "int"},
)
async def _prim_extract_list(
    text: str, hint: str = "", max_items: int = 30,
) -> dict[str, Any]:
    if not text:
        return {"items": [], "count": 0}
    section = _find_section(text, hint)
    items: list[str] = []
    seen: set[str] = set()

    # First pass: lines that match a bullet pattern.
    for raw in section.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = _BULLET_RE.match(line)
        if m is None:
            continue
        item = line[m.end():].strip()
        # Trim trailing trailing punctuation noise commonly left over (.,;)
        item = item.rstrip(".,;").strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
        if len(items) >= max_items:
            break

    # Fallback: if bullets gave us nothing AND the source looks like
    # comma-separated list ("a, b, c, d"), split on commas / newlines.
    if not items:
        flat = section.replace("\n", ",")
        parts = [p.strip().rstrip(".") for p in flat.split(",")]
        for p in parts:
            if not p or len(p) > 80:  # skip noise
                continue
            key = p.lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(p)
            if len(items) >= max_items:
                break

    return {"items": items, "count": len(items)}


# ---------------------------------------------------------------------------
# 2) summarize — extractive top-N sentences
# ---------------------------------------------------------------------------


@primitive(
    name="summarize",
    description=(
        "Riassume un testo in N frasi (default 3) usando estrattivo "
        "deterministico (no LLM). Adatto a articoli, news, lunghe email."
    ),
    args_schema={"text": "string", "max_sentences": "int"},
    returns_schema={"summary": "string", "sentence_count": "int"},
)
async def _prim_summarize(
    text: str, max_sentences: int = 3,
) -> dict[str, Any]:
    if not text:
        return {"summary": "", "sentence_count": 0}
    n = max(1, min(int(max_sentences), 12))
    summary = extract_top_sentences(text, k=n, max_chars=2000).strip()
    if not summary:
        return {"summary": "", "sentence_count": 0}
    # Each sentence ends in . ! or ? — count those terminators.
    sentence_count = sum(summary.count(p) for p in ".!?")
    if sentence_count == 0:
        sentence_count = 1
    return {"summary": summary, "sentence_count": min(sentence_count, n)}


# ---------------------------------------------------------------------------
# 3) ask_user — clarification scaffolder
# ---------------------------------------------------------------------------


@primitive(
    name="ask_user",
    description=(
        "Restituisce un marker che la skill espone come domanda all'utente. "
        "Il response_template della skill deve interpolare `{step.prompt}` "
        "(e opzionalmente `{step.choices_text}`) per surfacing. Il flow "
        "termina qui senza altre call. `choices` opzionale per liste a "
        "tap-singolo."
    ),
    args_schema={"prompt": "string", "choices": "list[str]"},
    returns_schema={
        "needs_input": "bool",
        "prompt": "string",
        "choices": "list[str]",
        "choices_text": "string",
    },
)
async def _prim_ask_user(
    prompt: str, choices: list[str] | None = None,
) -> dict[str, Any]:
    raw = (prompt or "").strip()
    items = [
        str(c).strip()
        for c in (choices or [])
        if c is not None and str(c).strip()
    ]
    choices_text = ""
    if items:
        choices_text = "\n".join(f"  • {c}" for c in items[:8])
    return {
        "needs_input": True,
        "prompt": raw or "Posso aiutarti con qualcosa di più specifico?",
        "choices": items,
        "choices_text": choices_text,
    }


# ---------------------------------------------------------------------------
# 4) read_url — fetch + clean + cap
# ---------------------------------------------------------------------------

USER_AGENT = "CARA-skill/1.0 (private home assistant)"

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<script[\s\S]*?</script>", re.IGNORECASE)
_STYLE_RE = re.compile(r"<style[\s\S]*?</style>", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _extract_with_trafilatura(html: str, url: str) -> tuple[str, str | None] | None:
    try:
        import trafilatura  # type: ignore[import-untyped]
    except ImportError:
        return None
    try:
        meta = trafilatura.metadata.extract_metadata(html, default_url=url)
        text = trafilatura.extract(
            html, include_comments=False, include_tables=False, no_fallback=False,
        )
        if not text or len(text) < 100:
            return None
        title = (meta.title if meta else None) or None
        return (text.strip(), title)
    except Exception as exc:  # noqa: BLE001
        log.debug("read_url.trafilatura_failed", url=url, error=str(exc))
        return None


def _extract_with_regex(html: str) -> tuple[str, str | None] | None:
    cleaned = _SCRIPT_RE.sub("", html)
    cleaned = _STYLE_RE.sub("", cleaned)
    text = _TAG_RE.sub(" ", cleaned)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 100:
        return None
    title_m = _TITLE_RE.search(html)
    title = title_m.group(1).strip() if title_m else None
    return (text, title)


@primitive(
    name="read_url",
    description=(
        "Scarica una pagina HTTP(S) e restituisce il testo principale "
        "estratto (trafilatura, fallback regex). Errori di rete / "
        "estrazione sono catturati e propagati come `fetched_ok=False` "
        "+ messaggio (la skill può poi decidere se andare avanti o "
        "abortire). Tronca a `max_chars` (default 8000)."
    ),
    args_schema={"url": "string", "max_chars": "int"},
    returns_schema={
        "text": "string",
        "title": "string",
        "source_domain": "string",
        "fetched_ok": "bool",
        "error": "string",
    },
)
async def _prim_read_url(
    url: str, max_chars: int = 8000,
) -> dict[str, Any]:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return {
            "text": "", "title": "", "source_domain": "",
            "fetched_ok": False, "error": "url non valido",
        }
    cap = max(500, min(int(max_chars), 64_000))
    domain = parsed.netloc.lower()

    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=8.0,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            r = await client.get(url)
            r.raise_for_status()
            html = r.text
    except Exception as exc:  # noqa: BLE001
        log.debug("read_url.fetch_failed", url=url, error=str(exc))
        return {
            "text": "", "title": "", "source_domain": domain,
            "fetched_ok": False, "error": f"fetch fallito: {exc}",
        }

    extracted = _extract_with_trafilatura(html, url) or _extract_with_regex(html)
    if extracted is None:
        return {
            "text": "", "title": "", "source_domain": domain,
            "fetched_ok": False, "error": "impossibile estrarre il testo",
        }
    text, title = extracted
    if len(text) > cap:
        text = text[:cap].rsplit(" ", 1)[0] + "…"
    return {
        "text": text,
        "title": title or "",
        "source_domain": domain,
        "fetched_ok": True,
        "error": "",
    }
