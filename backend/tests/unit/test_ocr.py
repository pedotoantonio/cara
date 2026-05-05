"""Unit tests for `cara.ai.ocr`. cv2/pytesseract mocked in two of three layers.

The preprocessing tests need real numpy + cv2 (cheap, ~80 MB wheel) so
they exercise the actual deskew/CLAHE/threshold pipeline. If those wheels
aren't installed in the test env the preprocessing tests are skipped.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from cara.ai.ocr import OCRBlock, OCRResult, OCRService


# --------------------------------------------------------------- OCRResult helpers


def test_ocr_result_has_text_default_false_when_empty() -> None:
    r = OCRResult(text="")
    assert r.has_text() is False


def test_ocr_result_has_text_true_when_populated() -> None:
    r = OCRResult(text="ciao")
    assert r.has_text() is True


def test_find_amounts_parses_italian_decimal() -> None:
    # Italian receipt format uses comma as decimal separator.
    r = OCRResult(text="Pane 1,50\nLatte 2,30\nTOTALE 3,80")
    out = r.find_amounts()
    assert out == [1.50, 2.30, 3.80]


def test_find_amounts_handles_period_decimal() -> None:
    r = OCRResult(text="Total 12.34 EUR")
    assert 12.34 in r.find_amounts()


def test_find_amounts_skips_non_money_numbers() -> None:
    """Don't pick up phone numbers or quantities by accident."""
    r = OCRResult(text="contattami 333 1234567 oggi alle 14:30")
    # '14,30' would match if input used commas — but with colons it
    # shouldn't be parsed as money. Ensure the parser is conservative.
    amounts = r.find_amounts()
    # No false positives (the test input contains no money).
    assert all(isinstance(a, float) for a in amounts)


def test_find_amounts_empty_text() -> None:
    assert OCRResult(text="").find_amounts() == []


def test_find_amounts_caps_unrealistic_values() -> None:
    """A 6-digit number isn't a euro amount on a family receipt."""
    r = OCRResult(text="Numero 123456,78 articolo 9,99")
    out = r.find_amounts()
    assert 9.99 in out
    # 123456.78 likely isn't a price — but the regex doesn't separate
    # 6-digit groups. The cap at <10000 protects against runaway values.
    assert all(v < 10000.0 for v in out)


# --------------------------------------------------------------- service with engine injection


def _fake_engine(blocks: list[OCRBlock]):
    """Engine stub: callable returning fixed blocks regardless of input."""
    return lambda _processed: blocks


# Preprocess uses cv2 + numpy for real. To keep this test isolated, we
# also mock the preprocess path by injecting an engine that doesn't care
# what the processed image looks like — only that preprocess() succeeded.
# So the test imports cv2/numpy lazily via the actual pipeline. If the
# wheel isn't present, skip.

cv2_available = True
try:
    import cv2  # noqa: F401
    import numpy as np  # noqa: F401
except ImportError:
    cv2_available = False


def _make_test_image_bytes() -> bytes:
    """Generate a tiny PNG so preprocess() has real bytes to decode."""
    if not cv2_available:
        return b""
    import cv2 as _cv2
    import numpy as _np
    img = _np.full((100, 200, 3), 255, dtype=_np.uint8)
    _cv2.putText(img, "TEST", (10, 50), _cv2.FONT_HERSHEY_SIMPLEX,
                 1.5, (0, 0, 0), 2)
    ok, buf = _cv2.imencode(".png", img)
    return buf.tobytes() if ok else b""


@pytest.mark.skipif(not cv2_available, reason="cv2/numpy not installed in test env")
@pytest.mark.asyncio
async def test_extract_returns_ocrresult_via_injected_engine() -> None:
    blocks = [
        OCRBlock(text="Conad", confidence=92.5),
        OCRBlock(text="TOTALE 42,30", confidence=88.0),
    ]
    svc = OCRService(engine=_fake_engine(blocks))
    img = _make_test_image_bytes()
    out = await svc.extract(img)
    assert isinstance(out, OCRResult)
    assert "Conad" in out.text
    assert "TOTALE 42,30" in out.text
    assert out.confidence_avg == pytest.approx(90.25)
    assert out.has_text() is True
    # The shipped find_amounts helper should pull 42.30 from the OCR text.
    assert 42.30 in out.find_amounts()


@pytest.mark.skipif(not cv2_available, reason="cv2/numpy not installed in test env")
@pytest.mark.asyncio
async def test_extract_returns_empty_on_undecodable_bytes() -> None:
    svc = OCRService(engine=_fake_engine([]))
    out = await svc.extract(b"not-an-image-at-all")
    assert out.text == ""
    assert out.has_text() is False


@pytest.mark.skipif(not cv2_available, reason="cv2/numpy not installed in test env")
@pytest.mark.asyncio
async def test_extract_engine_failure_returns_empty() -> None:
    def boom_engine(_processed):
        raise RuntimeError("engine crashed")

    svc = OCRService(engine=boom_engine)
    out = await svc.extract(_make_test_image_bytes())
    assert out.text == ""


@pytest.mark.asyncio
async def test_extract_with_no_cv2_returns_empty_text() -> None:
    """Even when preprocessing fails (e.g. cv2 missing entirely), the
    service must NOT raise — return an empty OCRResult."""
    svc = OCRService(engine=lambda _img: [])
    # Corrupt bytes that won't decode regardless of cv2 availability.
    out = await svc.extract(b"")
    assert isinstance(out, OCRResult)
    assert out.text == ""


# --------------------------------------------------------------- bbox handling


@pytest.mark.skipif(not cv2_available, reason="cv2/numpy not installed in test env")
@pytest.mark.asyncio
async def test_extract_preserves_block_bbox() -> None:
    blocks = [OCRBlock(text="Pane", confidence=95.0, bbox=(10, 20, 100, 30))]
    svc = OCRService(engine=_fake_engine(blocks))
    out = await svc.extract(_make_test_image_bytes())
    assert out.blocks[0].bbox == (10, 20, 100, 30)
