"""Unit tests for `cara.api.v1._chat_system_prompt`."""

from __future__ import annotations

import pytest

from cara.api.v1._chat_system_prompt import (
    SystemPromptSegments,
    build_facts_block,
    build_segments,
)


# ---------------------------------------------------------------- build_facts_block


def test_build_facts_block_empty_returns_empty_string() -> None:
    assert build_facts_block(None) == ""
    assert build_facts_block([]) == ""
    assert build_facts_block(["", "  "]) == ""


def test_build_facts_block_renders_bullet_list() -> None:
    out = build_facts_block(["È allergico ai pomodori", "Mi piace il caffè"])
    assert "- È allergico ai pomodori" in out
    assert "- Mi piace il caffè" in out
    assert "FATTI" in out


def test_build_facts_block_with_user_name_in_header() -> None:
    out = build_facts_block(["A"], user_name="Antonio")
    assert "ANTONIO" in out


def test_build_facts_block_strips_whitespace() -> None:
    out = build_facts_block(["  X  ", "Y"])
    # Each line should have the leading/trailing whitespace removed.
    assert "- X" in out
    assert "  X  " not in out


# ---------------------------------------------------------------- build_segments


def test_build_segments_basic() -> None:
    seg = build_segments(
        base_prompt="Sei CARA, l'assistente di casa.",
        include_runtime_context=False,
    )
    assert seg.base == "Sei CARA, l'assistente di casa."
    assert seg.tone == ""           # default tone is empty string
    assert seg.facts == ""           # no facts, no runtime context


def test_build_segments_assemble_omits_empty_layers() -> None:
    seg = build_segments(base_prompt="Base", include_runtime_context=False)
    out = seg.assemble()
    assert out.strip() == "Base"     # tone + facts empty → only base in output


def test_build_segments_with_tone_and_facts() -> None:
    seg = build_segments(
        base_prompt="Base.",
        tone_key="privacy",
        user_facts=["allergico ai pomodori"],
        user_name="Antonio",
        include_runtime_context=False,
    )
    assert "Base" in seg.base
    assert "PRIVACY ATTIVA" in seg.tone
    assert "ANTONIO" in seg.facts
    assert "allergico ai pomodori" in seg.facts


def test_build_segments_unknown_tone_key_falls_back_to_empty() -> None:
    seg = build_segments(
        base_prompt="Base", tone_key="some_unknown_tone",
        include_runtime_context=False,
    )
    assert seg.tone == ""


def test_build_segments_runtime_context_appended_to_facts() -> None:
    seg = build_segments(base_prompt="Base", include_runtime_context=True)
    assert "CONTESTO RUNTIME" in seg.facts
    # And the base / tone are unaffected by the runtime block.
    assert "Base" in seg.base
    assert seg.tone == ""


# ---------------------------------------------------------------- KV-cache fingerprint


def test_fingerprint_stable_across_facts_changes() -> None:
    """Same base + same tone, different facts → same fingerprint.

    This is the core property: KV cache is keyed on `stable_prefix`,
    which excludes facts/runtime context, so changing those should
    NOT invalidate the cache.
    """
    seg_a = build_segments(
        base_prompt="Base.", tone_key="default",
        user_facts=["fact A"], include_runtime_context=False,
    )
    seg_b = build_segments(
        base_prompt="Base.", tone_key="default",
        user_facts=["fact B", "fact C"], include_runtime_context=False,
    )
    assert seg_a.fingerprint() == seg_b.fingerprint()


def test_fingerprint_changes_when_base_changes() -> None:
    """Admin edits llm_system_prompt → fingerprint changes → cache flush."""
    seg_a = build_segments(base_prompt="Base v1", include_runtime_context=False)
    seg_b = build_segments(base_prompt="Base v2", include_runtime_context=False)
    assert seg_a.fingerprint() != seg_b.fingerprint()


def test_fingerprint_changes_when_tone_changes() -> None:
    """User switches privacy mode on → fingerprint changes."""
    seg_a = build_segments(
        base_prompt="Base", tone_key="default", include_runtime_context=False,
    )
    seg_b = build_segments(
        base_prompt="Base", tone_key="privacy", include_runtime_context=False,
    )
    assert seg_a.fingerprint() != seg_b.fingerprint()


def test_fingerprint_short_and_hex() -> None:
    seg = build_segments(base_prompt="X", include_runtime_context=False)
    fp = seg.fingerprint()
    assert len(fp) == 16
    assert all(c in "0123456789abcdef" for c in fp)


# ---------------------------------------------------------------- assemble ordering


def test_assemble_orders_base_tone_facts() -> None:
    seg = build_segments(
        base_prompt="==BASE==",
        tone_key="privacy",
        user_facts=["==FACT=="],
        include_runtime_context=False,
    )
    out = seg.assemble()
    base_pos = out.find("==BASE==")
    tone_pos = out.find("PRIVACY ATTIVA")
    facts_pos = out.find("==FACT==")
    assert base_pos < tone_pos < facts_pos


def test_assemble_handles_empty_tone_gracefully() -> None:
    """No tone → assemble produces (base) (facts) without an empty line in between."""
    seg = build_segments(
        base_prompt="Base", tone_key="default",
        user_facts=["F1"], include_runtime_context=False,
    )
    out = seg.assemble()
    # No triple-newline runs (would indicate an empty segment leaked through).
    assert "\n\n\n" not in out


# ---------------------------------------------------------------- direct dataclass


def test_segments_dataclass_round_trip() -> None:
    seg = SystemPromptSegments(base="A", tone="B", facts="C")
    assert seg.assemble() == "A\n\nB\n\nC"
    assert seg.stable_prefix() == "A\n\nB"
    assert len(seg.fingerprint()) == 16
