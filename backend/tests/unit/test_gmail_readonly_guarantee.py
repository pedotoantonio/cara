"""Regression test: Cara MUST NEVER modify Gmail messages.

The user's expectation is that an email which is "unread" on Gmail
stays unread after Cara has extracted a task proposal from it. This is
guaranteed at three levels:

  1. OAuth scope (`gmail.readonly` + `gmail.metadata`) — Google itself
     refuses any modify call.
  2. API wrapper (`cara/integrations/google_gmail.py`) exposes ONLY
     read-only helpers.
  3. Scanner (`cara/services/integrations/gmail_scanner.py`) only
     calls those read-only helpers.

This test grep-asserts the absence of any write-class endpoint in the
two modules. If a future PR introduces `messages.modify`, this test
fires and forces a deliberate decision (scope change + admin toggle +
privacy review).
"""

from __future__ import annotations

from pathlib import Path

import pytest


_FORBIDDEN_SUBSTRINGS = (
    # Methods that mutate Gmail state.
    "messages.modify",
    "messages.batchModify",
    "messages.trash",
    "messages.untrash",
    "messages.delete",
    "messages.send",
    "messages.batchDelete",
    # Equivalent URL fragments (in case someone bypasses helpers and
    # hits the REST endpoint directly).
    "/modify",
    "/trash",
    "/untrash",
    "/batchModify",
    "/batchDelete",
    "/send",
    # The "remove UNREAD label" path used by some libs.
    "removeLabelIds",
)


_FILES_TO_GUARD = (
    Path("cara/integrations/google_gmail.py"),
    Path("cara/services/integrations/gmail_scanner.py"),
    Path("cara/services/integrations/email_understanding.py"),
)


@pytest.fixture
def repo_root() -> Path:
    # tests/unit → tests → repo root
    return Path(__file__).resolve().parents[2]


def _strip_docstrings_and_comments(src: str) -> list[tuple[int, str]]:
    """Return [(lineno, code_line)] excluding docstrings and `#` comments.

    Lex-simple state machine: enough for the well-behaved Python files
    we're guarding (no exotic multi-line string usage outside docstrings).
    """
    out: list[tuple[int, str]] = []
    in_triple: str | None = None
    for lineno, raw in enumerate(src.splitlines(), start=1):
        line = raw
        stripped = line.strip()
        if not stripped:
            continue
        if in_triple is not None:
            if in_triple in line:
                in_triple = None
            continue
        # Strip trailing inline comments.
        if "#" in line:
            line = line.split("#", 1)[0]
            stripped = line.strip()
            if not stripped:
                continue
        # Open of a triple quote on this line?
        for q in ('"""', "'''"):
            first = line.find(q)
            if first == -1:
                continue
            second = line.find(q, first + 3)
            if second != -1:
                # Single-line docstring on this line.
                line = line[:first] + line[second + 3:]
            else:
                in_triple = q
                line = line[:first]
            stripped = line.strip()
            break
        if stripped:
            out.append((lineno, line))
    return out


@pytest.mark.parametrize("rel_path", _FILES_TO_GUARD)
def test_no_gmail_write_calls(repo_root: Path, rel_path: Path) -> None:
    full = repo_root / rel_path
    assert full.exists(), f"file missing: {full}"
    src = full.read_text(encoding="utf-8")
    code_lines = _strip_docstrings_and_comments(src)
    for lineno, line in code_lines:
        low = line.lower()
        for needle in _FORBIDDEN_SUBSTRINGS:
            if needle in low:
                pytest.fail(
                    f"{rel_path}:{lineno} contains forbidden Gmail write "
                    f"reference {needle!r}: {line.strip()}"
                )


def test_oauth_scope_set_is_readonly() -> None:
    """The 'gmail:ro' preset must contain ONLY read-only scopes."""
    from cara.integrations.google_oauth import SCOPE_PRESETS

    scopes = SCOPE_PRESETS["gmail:ro"]
    for s in scopes:
        # openid / email are identity scopes (no Gmail access)
        if s in ("openid", "email"):
            continue
        assert s.startswith("https://www.googleapis.com/auth/gmail."), s
        # Must be readonly or metadata. Anything else (modify, send,
        # compose, labels) would let us mutate.
        assert s.endswith(("/gmail.readonly", "/gmail.metadata")), (
            f"non-readonly scope in gmail:ro preset: {s}"
        )
