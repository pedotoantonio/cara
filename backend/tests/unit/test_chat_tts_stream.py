"""Unit tests for `cara.api.v1._chat_tts_stream` — SentenceBuffer logic.

The TTS synthesis itself is deferred (lazy import in the module);
these tests cover the deterministic sentence-extraction logic.
"""

from __future__ import annotations

import base64

from cara.api.v1._chat_tts_stream import (
    SentenceBuffer,
    audio_chunk_payload,
)


# ---------------------------------------------------------------- happy paths


def test_no_input_emits_nothing() -> None:
    buf = SentenceBuffer()
    assert buf.feed("") == []
    assert buf.flush() == []


def test_single_short_sentence_emitted_when_period_arrives() -> None:
    buf = SentenceBuffer()
    assert buf.feed("Ciao Antonio") == []     # no terminator yet
    out = buf.feed(", come stai?")
    assert out == ["Ciao Antonio, come stai?"]


def test_two_sentences_in_one_feed() -> None:
    buf = SentenceBuffer()
    out = buf.feed("Tutto bene grazie. E tu, come stai?")
    assert len(out) == 2
    assert out[0] == "Tutto bene grazie."
    assert out[1] == "E tu, come stai?"


def test_exclamation_and_question_split() -> None:
    buf = SentenceBuffer()
    out = buf.feed(
        "Davvero impressionante! Hai ragione? Sono d'accordo."
    )
    assert out == [
        "Davvero impressionante!",
        "Hai ragione?",
        "Sono d'accordo.",
    ]


def test_newline_acts_as_sentence_break() -> None:
    """Paragraph break is also a flush trigger — long enough buffer required."""
    buf = SentenceBuffer()
    out = buf.feed("Prima riga di un certo numero di caratteri\nseconda riga")
    # First chunk reached the newline and length > min, so it flushes.
    assert "Prima riga di un certo numero di caratteri" in out[0]


def test_flush_at_end_picks_up_unterminated_tail() -> None:
    buf = SentenceBuffer()
    buf.feed("La risposta finale senza punto")
    tail = buf.flush()
    assert tail == ["La risposta finale senza punto"]


def test_flush_after_complete_sentence_returns_empty() -> None:
    buf = SentenceBuffer()
    buf.feed("Tutto qui.")
    # The complete sentence already consumed by feed()'s return value.
    # Flush leaves nothing.
    assert buf.flush() == []


# ---------------------------------------------------------------- abbreviation handling


def test_abbreviation_es_does_not_trigger_split() -> None:
    """'es.' must NOT count as a sentence boundary even though it ends with a period."""
    buf = SentenceBuffer()
    out = buf.feed("Per es. la pasta è pronta.")
    # Only ONE sentence emitted, ending at the real period.
    assert out == ["Per es. la pasta è pronta."]


def test_abbreviation_sig_does_not_trigger_split() -> None:
    buf = SentenceBuffer()
    out = buf.feed("Sig. Rossi ha telefonato oggi.")
    assert out == ["Sig. Rossi ha telefonato oggi."]


def test_decimal_number_does_not_trigger_split() -> None:
    buf = SentenceBuffer()
    out = buf.feed("La temperatura è di 22.5 gradi adesso.")
    assert out == ["La temperatura è di 22.5 gradi adesso."]


# ---------------------------------------------------------------- length thresholds


def test_period_below_minimum_threshold_held() -> None:
    """Very short fragment ending in '.' is held — likely an abbreviation."""
    buf = SentenceBuffer()
    out = buf.feed("Sì.")
    # Below 12 chars — held; flush should release it.
    assert out == []
    assert buf.flush() == ["Sì."]


def test_max_length_force_flush() -> None:
    """A runaway buffer past 400 chars flushes even without punctuation."""
    long_text = "parola " * 80   # 560 chars, no terminator
    buf = SentenceBuffer()
    out = buf.feed(long_text)
    assert len(out) >= 1
    # Each emitted chunk must be ≤ the buffer ceiling.
    for s in out:
        assert len(s) <= 420


def test_max_length_falls_back_to_min_when_no_space() -> None:
    """Wall-of-text without spaces still gets cut at the ceiling."""
    buf = SentenceBuffer()
    out = buf.feed("x" * 500)
    assert out  # something was emitted, doesn't crash


# ---------------------------------------------------------------- streaming token-by-token


def test_token_by_token_feed_assembles_sentences() -> None:
    """Real LLM streaming: tokens arrive one at a time."""
    tokens = [
        "Ciao", " Antonio", ",", " come", " stai", "?", " Tutto",
        " bene", " grazie", ".",
    ]
    buf = SentenceBuffer()
    sentences: list[str] = []
    for t in tokens:
        sentences.extend(buf.feed(t))
    sentences.extend(buf.flush())
    assert "Ciao Antonio, come stai?" in sentences
    assert "Tutto bene grazie." in sentences


def test_seq_counter_increments_per_emitted_sentence() -> None:
    buf = SentenceBuffer()
    assert buf.next_seq == 0
    buf.feed("Una frase completa qui.")
    assert buf.next_seq == 1
    buf.feed("Un'altra frase qui.")
    assert buf.next_seq == 2


# ---------------------------------------------------------------- audio_chunk_payload


def test_audio_chunk_payload_shape() -> None:
    audio = b"RIFFfake-wav-bytes"
    out = audio_chunk_payload(
        seq=3, text="Ciao", audio_bytes=audio, voice_id="it_IT-paola-medium",
    )
    assert out["seq"] == 3
    assert out["text"] == "Ciao"
    assert out["voice_id"] == "it_IT-paola-medium"
    assert out["format"] == "wav"
    assert out["bytes"] == len(audio)
    # Round-trip the base64.
    assert base64.b64decode(out["audio_b64"]) == audio


def test_audio_chunk_payload_empty_audio() -> None:
    out = audio_chunk_payload(seq=0, text="", audio_bytes=b"", voice_id="x")
    assert out["bytes"] == 0
    assert out["audio_b64"] == ""
