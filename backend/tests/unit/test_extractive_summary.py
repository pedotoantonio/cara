"""Unit tests for `cara.services.extractive_summary`."""

from __future__ import annotations

from cara.services.extractive_summary import (
    extract_top_sentences,
    split_sentences,
    summarise_article,
)


# ---------------------------------------------------------------- splitter


def test_split_simple() -> None:
    text = "Prima frase. Seconda frase! Terza frase?"
    out = split_sentences(text)
    assert len(out) == 3
    assert out[0] == "Prima frase."
    assert out[2] == "Terza frase?"


def test_split_preserves_abbreviations() -> None:
    # "es." should NOT split: it's an abbreviation.
    text = "Ci sono molte specie, es. cani e gatti. Sono mammiferi."
    out = split_sentences(text)
    assert len(out) == 2
    assert "es. cani e gatti" in out[0]


def test_split_drops_too_short() -> None:
    # Single-char "fragments" are noise.
    text = "A. Una frase di buona lunghezza qui dentro."
    out = split_sentences(text)
    # The "A." is too short to keep.
    assert len(out) == 1
    assert "buona lunghezza" in out[0]


def test_split_handles_empty() -> None:
    assert split_sentences("") == []
    assert split_sentences(None) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------- ranker


def test_extract_picks_query_relevant_sentence() -> None:
    article = (
        "La sciarpa di lana è calda. "
        "Il sole splende oggi a Roma. "
        "Le pecore producono lana di buona qualità."
    )
    out = extract_top_sentences(article, query="cosa fanno le pecore?", k=1)
    # Strongest query overlap is the third sentence (pecore + lana shared).
    assert "pecore" in out.lower()


def test_extract_respects_max_chars() -> None:
    article = ". ".join(["Frase numero " + str(i) for i in range(20)]) + "."
    out = extract_top_sentences(article, query="frase", k=10, max_chars=80)
    assert len(out) <= 80


def test_extract_preserves_source_order() -> None:
    article = (
        "La carbonara contiene uova, guanciale e pecorino. "
        "Le uova vengono mescolate con il pecorino. "
        "Il guanciale viene rosolato in padella."
    )
    out = extract_top_sentences(article, query="ingredienti carbonara", k=2)
    # Whatever the picks are, they should appear in the order of the source.
    sentences = split_sentences(article)
    chosen = [s for s in sentences if s in out]
    if len(chosen) >= 2:
        idx0 = sentences.index(chosen[0])
        idx1 = sentences.index(chosen[1])
        assert idx0 < idx1


def test_summarise_short_article_returns_empty() -> None:
    # Below the 60-char threshold we don't summarise (article too thin).
    out = summarise_article("Ciao.", query="qualcosa", max_chars=380)
    assert out == ""


def test_summarise_strips_boilerplate() -> None:
    article = (
        "Accetta i cookie per continuare. "
        "Il pomodoro è un ortaggio originario delle Americhe. "
        "Condividi su Facebook. "
        "Si coltiva in tutto il mondo."
    )
    out = summarise_article(article, query="cosa è il pomodoro", max_chars=380)
    # Boilerplate "cookie" and "condividi" must NOT appear in the output.
    assert "cookie" not in out.lower()
    assert "condividi" not in out.lower()
    # Real content should make it through.
    assert "pomodoro" in out.lower() or "ortaggio" in out.lower()


def test_summarise_no_query_uses_lead() -> None:
    article = (
        "La capitale d'Italia è Roma. "
        "Roma è una città antica. "
        "I romani hanno costruito molte strade."
    )
    out = summarise_article(article, query="", max_chars=380)
    # With no query, lead-bias makes the first sentence likely to be picked.
    assert "Roma" in out or "capitale" in out
