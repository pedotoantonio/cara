"""Unit tests for `cara.ai.tts.normalizer`."""

from __future__ import annotations

import pytest

from cara.ai.tts.normalizer import TTSNormalizer, _apply_case, get_global_normalizer


def test_apply_case_preserves_uppercase() -> None:
    assert _apply_case("WEEKEND", "uìkend") == "UÌKEND"


def test_apply_case_preserves_titlecase() -> None:
    assert _apply_case("Weekend", "uìkend") == "Uìkend"


def test_apply_case_passes_lowercase_through() -> None:
    assert _apply_case("weekend", "uìkend") == "uìkend"


def test_normalize_swaps_known_word() -> None:
    n = TTSNormalizer({"weekend": "uìkend"})
    assert n.normalize("Vado in vacanza il weekend.") == "Vado in vacanza il uìkend."


def test_normalize_is_case_insensitive() -> None:
    n = TTSNormalizer({"weekend": "uìkend"})
    assert n.normalize("WEEKEND") == "UÌKEND"
    assert n.normalize("Weekend") == "Uìkend"
    assert n.normalize("weekend") == "uìkend"


def test_normalize_word_boundary_no_partial_match() -> None:
    n = TTSNormalizer({"app": "èp"})
    # Must NOT replace inside 'happy' or 'application'.
    assert n.normalize("happy application") == "happy application"
    # Must replace standalone 'app'.
    assert n.normalize("apri l'app") == "apri l'èp"


def test_normalize_empty_input_returns_empty() -> None:
    n = TTSNormalizer({"weekend": "uìkend"})
    assert n.normalize("") == ""


def test_normalize_empty_dict_passes_through() -> None:
    n = TTSNormalizer({})
    assert n.normalize("Hello weekend") == "Hello weekend"


def test_normalize_handles_punctuation() -> None:
    n = TTSNormalizer({"weekend": "uìkend"})
    assert n.normalize("weekend!") == "uìkend!"
    assert n.normalize("(weekend)") == "(uìkend)"
    assert n.normalize("weekend,") == "uìkend,"


def test_user_override_wins_over_base() -> None:
    n = TTSNormalizer({"weekend": "uìkend"})
    n.set_user_overrides({"weekend": "fineSettimana"})
    assert n.normalize("il weekend") == "il fineSettimana"


def test_user_override_empty_string_deletes_base_entry() -> None:
    n = TTSNormalizer({"weekend": "uìkend", "manager": "mànager"})
    n.set_user_overrides({"weekend": ""})
    assert n.normalize("manager weekend") == "mànager weekend"


def test_set_user_overrides_replaces_layer_atomically() -> None:
    n = TTSNormalizer({"weekend": "uìkend"})
    n.set_user_overrides({"manager": "mànager"})
    n.set_user_overrides({"meeting": "mìting"})  # replaces, doesn't extend
    assert n.lookup("meeting") == "mìting"
    assert n.lookup("manager") is None  # gone after the replace
    assert n.lookup("weekend") == "uìkend"  # base layer untouched


def test_merge_user_overrides_extends_layer() -> None:
    n = TTSNormalizer({"weekend": "uìkend"})
    n.merge_user_overrides({"manager": "mànager"})
    n.merge_user_overrides({"meeting": "mìting"})
    assert n.lookup("manager") == "mànager"
    assert n.lookup("meeting") == "mìting"


def test_size_reflects_effective_dict() -> None:
    n = TTSNormalizer({"a": "x", "b": "y"})
    assert n.size == 2
    n.merge_user_overrides({"c": "z"})
    assert n.size == 3
    n.set_user_overrides({"a": ""})  # deletes
    assert n.size == 1  # only 'b' left


def test_lookup_returns_replacement_or_none() -> None:
    n = TTSNormalizer({"weekend": "uìkend"})
    assert n.lookup("Weekend") == "uìkend"
    assert n.lookup("WEEKEND ") == "uìkend"  # whitespace tolerant
    assert n.lookup("nope") is None


def test_global_normalizer_loads_shipped_dictionary() -> None:
    """The shipped YAML loads and contains the canonical sample words."""
    g = get_global_normalizer()
    assert g.size > 100, "anglicisms.yaml should have hundreds of entries"
    # Sanity: a few high-confidence entries are present.
    assert g.lookup("weekend") is not None
    assert g.lookup("smartphone") is not None
    assert g.lookup("email") is not None


def test_global_normalizer_real_sentence() -> None:
    """End-to-end: a sentence with several anglicisms gets each one rewritten."""
    g = get_global_normalizer()
    out = g.normalize("Stasera ho un meeting con il manager dopo il weekend.")
    # Each of the three loanwords should be substituted (not equal to the
    # original spelling). We don't assert the exact phonetic spelling
    # because the dictionary is curated and may be tuned.
    assert "meeting" not in out.lower() or "mìting" in out.lower()
    assert "manager" not in out.lower() or "mànager" in out.lower()
    assert "weekend" not in out.lower() or "uìkend" in out.lower()


def test_normalize_is_idempotent_on_substituted_text() -> None:
    """Running the substitution twice on the same input shouldn't change it
    further (the phonetic spelling itself isn't a key)."""
    g = get_global_normalizer()
    once = g.normalize("Apri l'app sul mio smartphone.")
    twice = g.normalize(once)
    assert once == twice
