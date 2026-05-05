"""Extractive sentence-ranking summariser (Step "quick wins" — May 2026).

The 1.5B Qwen reliably hallucinates Italian terms when asked to *re-write*
a fetched article ("fotolettura", "uniretta", "Chloroplast in italiano"
seen in production). Replacing the second-pass synthesis with extractive
selection — pick the 1-3 most query-relevant sentences from the article
and quote them verbatim — eliminates the hallucination class entirely.

Algorithm (TextRank-lite + query overlap):

1. Split into sentences (Italian-aware: handles "etc.", "es.", common
   abbreviations).
2. Tokenise each sentence to a bag-of-words (lowercased, stop-words
   removed).
3. Score each sentence as:
      score(s) = α * query_overlap(s, q) + β * centrality(s)
   where centrality is sum of cosine similarities to all other sentences,
   approximated by Jaccard for speed.
4. Pick the top-k sentences (default 2), preserving original order.
5. Truncate the result if it's still over `max_chars` (default 380).

Returns plain text. Caller wraps in attribution and ships to the user.
No LLM, no GPU, ~2-5 ms for a 5KB article on the NanoPC.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

# Italian stop-words. Conservative: we keep meaningful nouns/adjectives
# but drop articles, prepositions, copulas, common adverbs.
_STOPWORDS_IT = frozenset({
    "a", "ad", "ai", "al", "alla", "alle", "agli", "allo", "anche", "ancora",
    "che", "chi", "ci", "ce", "co", "col", "come", "con", "contro", "cui",
    "da", "dai", "dal", "dalla", "dalle", "dagli", "dallo", "del", "dei",
    "della", "delle", "degli", "dello", "di", "dove", "due", "e", "è", "ed",
    "essere", "fa", "fino", "fra", "gli", "ha", "hai", "ho", "il", "i", "in",
    "io", "la", "le", "lei", "li", "lo", "loro", "lui", "ma", "mai", "me",
    "mi", "mio", "mia", "mie", "miei", "ne", "né", "nei", "nel", "nella",
    "nelle", "negli", "nello", "no", "noi", "non", "nostre", "nostri", "nostro",
    "o", "od", "ogni", "or", "ora", "per", "però", "più", "poi", "qua", "quale",
    "quali", "qualcosa", "quasi", "quel", "quella", "quelle", "quelli", "quello",
    "questa", "queste", "questi", "questo", "qui", "se", "sei", "senza", "si",
    "sia", "siamo", "siate", "siete", "sono", "sta", "stai", "stanno", "stata",
    "stati", "stato", "su", "sua", "sue", "sugli", "sui", "sul", "sulla",
    "sulle", "sullo", "suo", "suoi", "te", "ti", "tra", "tre", "tu", "tua",
    "tue", "tuo", "tuoi", "tutti", "tutto", "un", "una", "uno", "vi", "voi",
    "vostra", "vostre", "vostri", "vostro",
    # Common conversational fillers in extracted articles.
    "dunque", "infatti", "inoltre", "tuttavia", "quindi", "perché", "perchè",
    "molto", "anche", "solo", "tutta", "tutte",
})


# Sentence splitter: matches `.`, `!`, `?`, or `;` followed by space + capital,
# but not after common Italian abbreviations (es., etc., dr., sig., ecc.).
_ABBREV_GUARD = re.compile(
    r"\b(?:es|etc|ecc|cfr|prof|dr|dott|sig|ing|a\.?\s?C|d\.?\s?C)\.\s*$",
    re.IGNORECASE,
)


def split_sentences(text: str) -> list[str]:
    """Split Italian prose into sentences, robust to common abbreviations."""
    # Normalise whitespace.
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []

    # Split on sentence enders, but stitch back when we landed inside an abbrev.
    parts: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        buf.append(ch)
        if ch in ".!?;":
            # Lookback: if we're inside an abbrev like "es.", continue.
            tail = "".join(buf)
            if _ABBREV_GUARD.search(tail):
                i += 1
                continue
            # Lookahead: if next char is space + capital/digit/quote, split.
            j = i + 1
            while j < len(text) and text[j] == " ":
                j += 1
            if j < len(text):
                nxt = text[j]
                if nxt.isupper() or nxt.isdigit() or nxt in "«\"'(":
                    parts.append(tail.strip())
                    buf = []
        i += 1
    if buf:
        rest = "".join(buf).strip()
        if rest:
            parts.append(rest)
    # Strip parts that are too short to be meaningful (e.g. just punctuation).
    return [p for p in parts if len(p) >= 12]


def _normalise_word(w: str) -> str:
    """Lowercase, strip diacritics, drop punctuation. Used for token compare."""
    w = w.lower().strip()
    # Strip diacritics so "città" matches "citta" if either appears.
    w = unicodedata.normalize("NFD", w)
    w = "".join(c for c in w if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\w]+", "", w)


def _tokenise(text: str) -> set[str]:
    """Bag-of-words. Stop-words and 1-char tokens removed."""
    raw = re.findall(r"[\w'-]+", text.lower())
    out: set[str] = set()
    for w in raw:
        norm = _normalise_word(w)
        if not norm or len(norm) <= 1:
            continue
        if norm in _STOPWORDS_IT:
            continue
        out.add(norm)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def extract_top_sentences(
    article: str,
    *,
    query: str = "",
    k: int = 2,
    max_chars: int = 380,
    alpha_query: float = 1.6,
    beta_centrality: float = 1.0,
) -> str:
    """Return up to `k` sentences from `article`, ranked by query relevance
    and centrality. Output preserves source order and is truncated to
    `max_chars` if needed.

    `query`: the user's question. Higher α boosts query overlap.
    `k`: max sentences picked (caller may override based on size).
    `max_chars`: hard char cap on the returned blob.
    """
    sentences = split_sentences(article)
    if not sentences:
        return ""

    q_tokens = _tokenise(query) if query else set()
    sent_tokens = [_tokenise(s) for s in sentences]

    # Centrality via average Jaccard to all other sentences. O(n²) but
    # n is small (typical article ≤ 60 sentences after splitting).
    n = len(sentences)
    centrality = [0.0] * n
    if n > 1 and beta_centrality > 0:
        for i in range(n):
            total = 0.0
            for j in range(n):
                if i == j:
                    continue
                total += _jaccard(sent_tokens[i], sent_tokens[j])
            centrality[i] = total / (n - 1)

    # Compose final score.
    scores: list[tuple[int, float]] = []
    for i, toks in enumerate(sent_tokens):
        q_overlap = _jaccard(toks, q_tokens) if q_tokens else 0.0
        score = alpha_query * q_overlap + beta_centrality * centrality[i]
        # Tiny prior for the first 3 sentences (often the "lead" of an
        # article — gives meaningful results when the query is very short).
        if i < 3:
            score += 0.05
        scores.append((i, score))

    # Top-k by score. Ties broken by original order (lower idx first).
    scores.sort(key=lambda t: (-t[1], t[0]))
    chosen_idx = sorted(idx for idx, _ in scores[:k])
    chosen = [sentences[i] for i in chosen_idx]

    out = " ".join(chosen).strip()

    # Char cap: if we overshoot, walk back to the last sentence that fits.
    if len(out) > max_chars:
        out = ""
        for s in chosen:
            cand = (out + " " + s).strip() if out else s
            if len(cand) > max_chars:
                if not out:
                    # Single sentence too long — hard truncate at word boundary.
                    out = _truncate_at_word(s, max_chars)
                break
            out = cand
    return out


def _truncate_at_word(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def summarise_article(
    article_text: str,
    *,
    query: str,
    title: str | None = None,
    max_chars: int = 380,
) -> str:
    """High-level entry: rank, pick, format. Fallback gracefully on empty.

    The output is plain Italian prose meant for direct display in a chat
    bubble. Caller appends the source attribution (`(fonte: domain)`).
    """
    if not article_text or len(article_text.strip()) < 60:
        return ""

    # Drop boilerplate that hurts ranking (cookie banners, share buttons, etc.).
    cleaned = _strip_boilerplate(article_text)

    # Pick how many sentences we afford. Roughly 1 sentence per ~150 chars
    # of cap, capped at 3 (more becomes a wall of quote).
    k = min(3, max(1, max_chars // 150))

    extract = extract_top_sentences(
        cleaned, query=query, k=k, max_chars=max_chars,
    )
    return extract


_BOILERPLATE_PATTERNS = [
    re.compile(r"\b(?:cookie|gdpr|privacy policy|accetta|accetto)[^.]*\.?",
               re.IGNORECASE),
    re.compile(r"\b(?:condividi su|seguici su|iscriviti alla newsletter)[^.]*\.?",
               re.IGNORECASE),
    re.compile(r"©\s*\d{4}[^.]*\.?"),
    re.compile(r"\bleggi anche\b[^.]*\.?", re.IGNORECASE),
    re.compile(r"\b(?:articolo correlato|articoli correlati)\b[^.]*\.?",
               re.IGNORECASE),
]


def _strip_boilerplate(text: str) -> str:
    """Remove common web-boilerplate sentences."""
    out = text
    for pat in _BOILERPLATE_PATTERNS:
        out = pat.sub(" ", out)
    return re.sub(r"\s+", " ", out).strip()


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------


__all__ = [
    "extract_top_sentences",
    "split_sentences",
    "summarise_article",
]
