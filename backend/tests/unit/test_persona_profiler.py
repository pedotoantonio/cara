"""Unit tests for `cara.learning.persona_profiler` — pure-function logic.

The LLM-touching paths (extract_from_chunk, merge, rebuild_for_user) need
a real `LLMService` + DB session and are out of scope for unit tests;
they're exercised by the nightly scheduler in production.

These tests cover:
- chunk_messages_token_aware sizing
- _format_chunk role filtering + content truncation
- _extract_confidence regex parsing
- _parse_sections + _bullets_to_buckets STABILE/EPISODICO classification
- _truncate_to_chars boundary behaviour
- get_for_prompt_injection gating (confidence floor, status filter)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cara.learning import persona_profiler as pp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(id_: int, content: str, role: str = "user", minutes_ago: int = 0) -> SimpleNamespace:
    """Cheap stand-in for `cara.models.Message` — only the attributes the
    profiler reads (id, content, role, created_at)."""
    return SimpleNamespace(
        id=id_,
        content=content,
        role=role,
        user_id=1,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def test_chunk_small_corpus_fits_in_one_chunk() -> None:
    msgs = [_msg(i, "ciao" * 5) for i in range(5)]
    chunks = pp.chunk_messages_token_aware(msgs, max_tokens_per_chunk=1500)
    assert len(chunks) == 1
    assert len(chunks[0]) == 5


def test_chunk_splits_when_overflowing() -> None:
    # Each msg ~500 chars → ~200 tokens. Cap at 500 tokens → 2-3 msgs per chunk.
    msgs = [_msg(i, "x" * 500) for i in range(10)]
    chunks = pp.chunk_messages_token_aware(msgs, max_tokens_per_chunk=500)
    assert len(chunks) >= 4
    # No chunk is empty and the union covers all messages.
    flat = [m for c in chunks for m in c]
    assert {m.id for m in flat} == set(range(10))


def test_chunk_keeps_oversize_single_message_intact() -> None:
    # A single 5000-char msg overflows the budget but is kept whole.
    msgs = [_msg(0, "x" * 5000), _msg(1, "small")]
    chunks = pp.chunk_messages_token_aware(msgs, max_tokens_per_chunk=500)
    # First chunk has the big one alone, second has the small.
    assert any(any(m.id == 0 for m in c) for c in chunks)
    assert any(any(m.id == 1 for m in c) for c in chunks)


# ---------------------------------------------------------------------------
# Format chunk
# ---------------------------------------------------------------------------


def test_format_chunk_filters_non_user_assistant_roles() -> None:
    msgs = [
        _msg(1, "ciao", role="user"),
        _msg(2, "salve", role="assistant"),
        _msg(3, "system note", role="system"),  # filtered
        _msg(4, "tool out", role="tool"),       # filtered
    ]
    out = pp._format_chunk(msgs)  # noqa: SLF001
    assert "ciao" in out
    assert "salve" in out
    assert "system note" not in out
    assert "tool out" not in out


def test_format_chunk_truncates_very_long_messages() -> None:
    long_text = "x" * 2000
    msgs = [_msg(1, long_text, role="user")]
    out = pp._format_chunk(msgs)  # noqa: SLF001
    assert "…" in out
    assert len(out) < 1500


# ---------------------------------------------------------------------------
# Confidence parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Confidenza: 78%", 78.0),
        ("...\nConfidenza: 0%", 0.0),
        ("Confidenza:  100 %", 100.0),
        ("Confidenza: 105%", 100.0),      # clamped
        ("Confidenza: -5%", None),         # negative not parsed (regex \d+)
        ("no marker", None),
    ],
)
def test_extract_confidence(text: str, expected: float | None) -> None:
    assert pp._extract_confidence(text) == expected  # noqa: SLF001


# ---------------------------------------------------------------------------
# Section parsing
# ---------------------------------------------------------------------------


def test_parse_sections_basic() -> None:
    md = (
        "## Identità\n"
        "- **STABILE** vive a Ferrara\n"
        "- **STABILE** lavora in fabbrica\n"
        "\n"
        "## Stato emotivo\n"
        "- **EPISODICO** [2026-05-20] giornata pesante\n"
        "- **EPISODICO** sereno la mattina\n"
        "\n"
        "Confidenza: 75%\n"
    )
    sections = pp._parse_sections(md)  # noqa: SLF001
    assert "Identità" in sections
    assert "Stato emotivo" in sections
    assert sections["Identità"]["stable"] == [
        "vive a Ferrara",
        "lavora in fabbrica",
    ]
    assert sections["Stato emotivo"]["episodic"][0] == {
        "date": "2026-05-20",
        "text": "giornata pesante",
    }
    assert sections["Stato emotivo"]["episodic"][1] == {
        "date": "",
        "text": "sereno la mattina",
    }


def test_parse_sections_handles_alternate_markers() -> None:
    md = (
        "## Lavoro\n"
        "- STABILE: ingegnere\n"
        "- [STABILE] turnista\n"
        "- *EPISODICO* [2026-05-19] ferie\n"
    )
    sections = pp._parse_sections(md)  # noqa: SLF001
    assert sections["Lavoro"]["stable"] == ["ingegnere", "turnista"]
    assert sections["Lavoro"]["episodic"] == [
        {"date": "2026-05-19", "text": "ferie"},
    ]


def test_parse_sections_handles_plain_bullets_as_stable() -> None:
    md = (
        "## Identità\n"
        "- vive a Bologna\n"
        "- 38 anni\n"
    )
    sections = pp._parse_sections(md)  # noqa: SLF001
    assert sections["Identità"]["stable"] == ["vive a Bologna", "38 anni"]
    assert sections["Identità"]["episodic"] == []


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


def test_truncate_returns_input_when_under_cap() -> None:
    text = "short text"
    assert pp._truncate_to_chars(text, 100) == text  # noqa: SLF001


def test_truncate_cuts_at_line_boundary_when_possible() -> None:
    text = "line1\nline2\nline3\n" + "x" * 200
    out = pp._truncate_to_chars(text, 50)  # noqa: SLF001
    assert "[…profilo troncato per limite di lunghezza]" in out
    # The last newline kept should be the one before the truncation cliff.
    assert out.startswith("line1\nline2\nline3")


# ---------------------------------------------------------------------------
# Token estimate
# ---------------------------------------------------------------------------


def test_approx_tokens_sane_range() -> None:
    # 100 chars → ~40 tokens at our 2.5 chars/token ratio.
    n = pp._approx_tokens("x" * 100)  # noqa: SLF001
    assert 35 < n < 45


# ---------------------------------------------------------------------------
# Prompt-injection gating
# ---------------------------------------------------------------------------


class _FakeSession:
    """Stand-in AsyncSession that returns a pre-set profile on `.get()`."""
    def __init__(self, profile):
        self._profile = profile

    async def get(self, _cls, _key):
        return self._profile


@pytest.mark.asyncio
async def test_get_for_injection_returns_none_when_no_profile() -> None:
    session = _FakeSession(None)
    out = await pp.get_for_prompt_injection(session, user_id=1)
    assert out is None


@pytest.mark.asyncio
async def test_get_for_injection_returns_none_when_low_confidence() -> None:
    profile = SimpleNamespace(
        markdown="## Identità\n- vive a Ferrara",
        confidence=40.0,
        last_status="ok",
    )
    session = _FakeSession(profile)
    out = await pp.get_for_prompt_injection(session, user_id=1)
    assert out is None


@pytest.mark.asyncio
async def test_get_for_injection_returns_none_on_failed_status() -> None:
    profile = SimpleNamespace(
        markdown="## Identità\n- vive a Ferrara",
        confidence=90.0,
        last_status="failed",
    )
    session = _FakeSession(profile)
    out = await pp.get_for_prompt_injection(session, user_id=1)
    assert out is None


@pytest.mark.asyncio
async def test_get_for_injection_returns_markdown_when_ok_and_confident() -> None:
    profile = SimpleNamespace(
        markdown="## Identità\n- **STABILE** vive a Ferrara",
        confidence=85.0,
        last_status="ok",
    )
    session = _FakeSession(profile)
    out = await pp.get_for_prompt_injection(session, user_id=1)
    assert out is not None
    assert "vive a Ferrara" in out


@pytest.mark.asyncio
async def test_get_for_injection_truncates_to_max_chars() -> None:
    profile = SimpleNamespace(
        markdown="## Identità\n" + ("a" * 5000),
        confidence=85.0,
        last_status="ok",
    )
    session = _FakeSession(profile)
    out = await pp.get_for_prompt_injection(session, user_id=1, max_chars=200)
    assert out is not None
    assert len(out) <= 260  # 200 + truncation marker
