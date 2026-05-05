"""Unit tests for the 4 generic Phase-B skill primitives."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

# Importing the module registers the primitives as a side-effect.
from cara.skills import primitives_generic  # noqa: F401
from cara.skills.registry import get_primitive, list_primitives


# ---------------------------------------------------------------------------
# Registration smoke
# ---------------------------------------------------------------------------


def test_all_four_generic_primitives_register() -> None:
    names = {p.name for p in list_primitives()}
    assert {"extract_list", "summarize", "ask_user", "read_url"}.issubset(names)


def test_extract_list_spec_has_expected_args() -> None:
    spec = get_primitive("extract_list")
    assert spec is not None
    assert set(spec.args_schema.keys()) == {"text", "hint", "max_items"}
    assert "items" in spec.returns_schema


# ---------------------------------------------------------------------------
# extract_list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_list_empty_text_returns_zero() -> None:
    out = await primitives_generic._prim_extract_list("")
    assert out == {"items": [], "count": 0}


@pytest.mark.asyncio
async def test_extract_list_dash_bullets() -> None:
    text = """
Lista della spesa:
- latte
- pane
- mele rosse
- caffè
"""
    out = await primitives_generic._prim_extract_list(text)
    assert out["count"] == 4
    assert out["items"] == ["latte", "pane", "mele rosse", "caffè"]


@pytest.mark.asyncio
async def test_extract_list_numbered_bullets() -> None:
    text = """
Cose da fare:
1. chiamare il dentista
2. prenotare ristorante
3) lavare la macchina
(4) comprare regalo
"""
    out = await primitives_generic._prim_extract_list(text)
    assert out["count"] == 4
    assert "chiamare il dentista" in out["items"]
    assert "comprare regalo" in out["items"]


@pytest.mark.asyncio
async def test_extract_list_unicode_bullets() -> None:
    text = "Menu:\n• antipasto\n• primo\n• secondo\n‣ dolce"
    out = await primitives_generic._prim_extract_list(text)
    assert out["count"] == 4


@pytest.mark.asyncio
async def test_extract_list_dedupe_case_insensitive() -> None:
    text = "- Pane\n- pane\n- PANE\n- Latte"
    out = await primitives_generic._prim_extract_list(text)
    assert out["count"] == 2
    assert out["items"][0].lower() == "pane"


@pytest.mark.asyncio
async def test_extract_list_max_items_cap() -> None:
    text = "\n".join(f"- item{i}" for i in range(50))
    out = await primitives_generic._prim_extract_list(text, max_items=5)
    assert out["count"] == 5


@pytest.mark.asyncio
async def test_extract_list_hint_targets_section() -> None:
    text = """
Introduzione:
- non rilevante
- nemmeno questa

Ingredienti:
- pasta
- pomodoro
- basilico
"""
    out = await primitives_generic._prim_extract_list(text, hint="ingredienti")
    assert out["count"] == 3
    assert "pasta" in out["items"]
    assert "non rilevante" not in out["items"]


@pytest.mark.asyncio
async def test_extract_list_comma_fallback() -> None:
    """No bullets at all → fallback to comma-split."""
    out = await primitives_generic._prim_extract_list(
        "latte, pane, caffè, frutta",
    )
    assert out["count"] == 4


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarize_empty_returns_empty() -> None:
    out = await primitives_generic._prim_summarize("")
    assert out == {"summary": "", "sentence_count": 0}


@pytest.mark.asyncio
async def test_summarize_short_input_returns_something() -> None:
    text = (
        "L'inverno scorso è stato il più freddo degli ultimi vent'anni. "
        "Le temperature sono scese sotto lo zero per settimane. "
        "Molte case hanno avuto problemi col riscaldamento. "
        "I tecnici hanno lavorato senza sosta. "
        "Anche le scuole sono state chiuse per due giorni."
    )
    out = await primitives_generic._prim_summarize(text, max_sentences=2)
    assert out["sentence_count"] >= 1
    assert out["sentence_count"] <= 2
    assert len(out["summary"]) > 0


@pytest.mark.asyncio
async def test_summarize_clamps_max_sentences() -> None:
    text = ". ".join([f"Frase numero {i}" for i in range(20)]) + "."
    out = await primitives_generic._prim_summarize(text, max_sentences=200)
    assert out["sentence_count"] <= 12  # internal clamp


# ---------------------------------------------------------------------------
# ask_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_user_basic() -> None:
    out = await primitives_generic._prim_ask_user("Quale ricetta?")
    assert out["needs_input"] is True
    assert out["prompt"] == "Quale ricetta?"
    assert out["choices"] == []
    assert out["choices_text"] == ""


@pytest.mark.asyncio
async def test_ask_user_with_choices_renders_bullet_text() -> None:
    out = await primitives_generic._prim_ask_user(
        "Quale lista?",
        choices=["Spesa", "Cose da fare", "Idee"],
    )
    assert out["choices"] == ["Spesa", "Cose da fare", "Idee"]
    assert "• Spesa" in out["choices_text"]
    assert "• Idee" in out["choices_text"]


@pytest.mark.asyncio
async def test_ask_user_falls_back_when_prompt_empty() -> None:
    out = await primitives_generic._prim_ask_user("")
    # Falls back to a sane default rather than empty string.
    assert "?" in out["prompt"]


@pytest.mark.asyncio
async def test_ask_user_drops_empty_choices() -> None:
    out = await primitives_generic._prim_ask_user(
        "test", choices=["", "  ", "ok", None],  # type: ignore[list-item]
    )
    assert out["choices"] == ["ok"]


# ---------------------------------------------------------------------------
# read_url
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_url_rejects_invalid_scheme() -> None:
    out = await primitives_generic._prim_read_url("ftp://nope")
    assert out["fetched_ok"] is False
    assert "non valido" in out["error"]


@pytest.mark.asyncio
async def test_read_url_rejects_empty() -> None:
    out = await primitives_generic._prim_read_url("")
    assert out["fetched_ok"] is False


@pytest.mark.asyncio
async def test_read_url_rejects_no_host() -> None:
    out = await primitives_generic._prim_read_url("https://")
    assert out["fetched_ok"] is False


@pytest.mark.asyncio
async def test_read_url_swallows_network_error() -> None:
    """Patch the AsyncClient to raise; we expect a structured failure."""
    import httpx

    class _FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            return False
        async def get(self, _url):
            raise httpx.ConnectError("simulated DNS failure")

    with patch("cara.skills.primitives_generic.httpx.AsyncClient", return_value=_FakeClient()):
        out = await primitives_generic._prim_read_url("https://example.com/page")
    assert out["fetched_ok"] is False
    assert out["source_domain"] == "example.com"
    assert "fetch fallito" in out["error"]


@pytest.mark.asyncio
async def test_read_url_extracts_via_regex_fallback() -> None:
    """Patch the trafilatura import path to fail and let the regex
    fallback do the work."""
    fake_html = (
        "<html><head><title>Mio Articolo</title></head>"
        "<body><script>nope</script>"
        "<p>" + ("Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 10)
        + "</p></body></html>"
    )

    class _Resp:
        text = fake_html
        def raise_for_status(self):
            return None

    class _FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            return False
        async def get(self, _url):
            return _Resp()

    with patch(
        "cara.skills.primitives_generic.httpx.AsyncClient",
        return_value=_FakeClient(),
    ), patch(
        "cara.skills.primitives_generic._extract_with_trafilatura",
        return_value=None,
    ):
        out = await primitives_generic._prim_read_url("https://news.example.com/123")

    assert out["fetched_ok"] is True
    assert out["source_domain"] == "news.example.com"
    assert "Mio Articolo" in out["title"]
    assert "Lorem ipsum" in out["text"]


@pytest.mark.asyncio
async def test_read_url_caps_text_length() -> None:
    long_html = (
        "<html><body><p>" + ("Frase x. " * 5000) + "</p></body></html>"
    )

    class _Resp:
        text = long_html
        def raise_for_status(self):
            return None

    class _FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            return False
        async def get(self, _url):
            return _Resp()

    with patch(
        "cara.skills.primitives_generic.httpx.AsyncClient",
        return_value=_FakeClient(),
    ), patch(
        "cara.skills.primitives_generic._extract_with_trafilatura",
        return_value=None,
    ):
        out = await primitives_generic._prim_read_url(
            "https://x.com/long", max_chars=500,
        )
    assert out["fetched_ok"] is True
    assert len(out["text"]) <= 502  # 500 + ellipsis & spacing slack


# Suppress an unused-import warning for AsyncMock if pyright complains.
_ = AsyncMock
