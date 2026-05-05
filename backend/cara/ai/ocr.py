"""OCR service — image → text via Tesseract, with OpenCV preprocessing.

Used by the receipt / bill / prescription / recipe-photo workflows. CPU-only
on the NanoPC, ~200-500 ms per receipt-sized image after preprocessing.

Pipeline:

    bytes → OpenCV decode → grayscale → deskew → contrast (CLAHE)
          → adaptive threshold → Tesseract (lang=ita+eng) → OCRResult

Preprocessing is what makes the difference between "Tesseract sees
random characters" and "Tesseract recognises the receipt total". The
defaults below are tuned for indoor phone photos of paper receipts: the
two most common failure modes are skew (camera not parallel to paper)
and low contrast (yellowish thermal paper).

Both `pytesseract` and `cv2` are imported lazily so unit tests don't
need the binaries. In production the backend Dockerfile must install
`tesseract-ocr tesseract-ocr-ita tesseract-ocr-eng poppler-utils` and
the `opencv-python-headless` + `pytesseract` Python wheels.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import structlog


log = structlog.get_logger(__name__)


# Tesseract config knobs that work well for receipts.
# `-l ita+eng` lets the engine accept English words (brand names,
# loanwords) without choking the Italian dictionary.
# `--psm 6` = "Assume a single uniform block of text". Good for receipts
# that are essentially one column of lines.
DEFAULT_TESSERACT_CONFIG = "--psm 6"
DEFAULT_LANGUAGES = "ita+eng"

# Italian-style decimal/currency patterns reused by receipt parsers.
_AMOUNT_RE = re.compile(r"(?<!\d)(?P<euros>\d{1,4})[.,](?P<cents>\d{2})(?!\d)")


@dataclass
class OCRBlock:
    """One line/block of recognised text with confidence."""
    text: str
    confidence: float  # 0.0 - 100.0 (Tesseract scale)
    bbox: tuple[int, int, int, int] | None = None  # (x, y, w, h)


@dataclass
class OCRResult:
    """Full output: raw text, per-block detail, language hint."""

    text: str
    blocks: list[OCRBlock] = field(default_factory=list)
    confidence_avg: float = 0.0
    languages: str = DEFAULT_LANGUAGES
    width: int = 0
    height: int = 0

    def has_text(self) -> bool:
        return bool(self.text.strip())

    def find_amounts(self) -> list[float]:
        """Quick helper — extract all € amounts from the OCR'd text.

        Returns a list of floats in document order. Useful for receipts:
        the LAST amount on a receipt is almost always the total.
        """
        out: list[float] = []
        for m in _AMOUNT_RE.finditer(self.text):
            try:
                value = float(f"{m.group('euros')}.{m.group('cents')}")
            except ValueError:
                continue
            # Reject obviously non-money matches (e.g., "12,5kg" left over)
            if value < 10000.0:
                out.append(value)
        return out


# ---------------------------------------------------------------------------
# Lazy imports — kept inside helper fns so test runs don't need the wheels
# ---------------------------------------------------------------------------


def _import_cv2():
    import cv2  # type: ignore[import-not-found]
    return cv2


def _import_pytesseract():
    import pytesseract  # type: ignore[import-not-found]
    return pytesseract


def _import_numpy():
    import numpy as np  # type: ignore[import-not-found]
    return np


# ---------------------------------------------------------------------------
# Preprocessing helpers (pure OpenCV, no Tesseract)
# ---------------------------------------------------------------------------


def _to_gray(img: Any) -> Any:
    cv2 = _import_cv2()
    if len(img.shape) == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _deskew(gray: Any, *, max_angle_deg: float = 10.0) -> Any:
    """Estimate skew via image moments and rotate to correct.

    Conservative: if the inferred angle is > `max_angle_deg`, skip
    rotation (likely a misdetection on noisy input).
    """
    cv2 = _import_cv2()
    np = _import_numpy()
    coords = np.column_stack(np.where(gray < 200))  # dark ink pixels
    if len(coords) < 50:
        return gray
    rect = cv2.minAreaRect(coords.astype(np.float32))
    angle = rect[-1]
    # cv2 returns angle in [-90, 0). Normalise.
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    if abs(angle) > max_angle_deg:
        return gray
    h, w = gray.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        gray, M, (w, h),
        flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE,
    )


def _enhance_contrast(gray: Any) -> Any:
    cv2 = _import_cv2()
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _binarise(gray: Any) -> Any:
    cv2 = _import_cv2()
    return cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=31, C=10,
    )


def preprocess(image_bytes: bytes) -> Any:
    """Run the full preprocessing pipeline on a raw image byte string.

    Returns the binarised grayscale image ready for Tesseract.
    """
    cv2 = _import_cv2()
    np = _import_numpy()
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("could not decode image bytes")
    gray = _to_gray(img)
    gray = _deskew(gray)
    gray = _enhance_contrast(gray)
    gray = _binarise(gray)
    return gray


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class OCRService:
    """High-level OCR API: image bytes → OCRResult.

    For tests, inject `engine=` (a callable that takes a numpy image and
    returns a list[OCRBlock]) so we don't need the actual Tesseract
    binary or pytesseract wheel.
    """

    def __init__(self, engine: Any | None = None, languages: str = DEFAULT_LANGUAGES) -> None:
        self._engine = engine
        self._languages = languages

    async def extract(self, image_bytes: bytes) -> OCRResult:
        """Decode + preprocess + OCR. Errors are logged and surfaced as empty."""
        try:
            processed = preprocess(image_bytes)
        except Exception as exc:  # noqa: BLE001
            log.warning("ocr.preprocess_failed", error=str(exc))
            return OCRResult(text="")

        try:
            blocks = self._run_engine(processed)
        except Exception as exc:  # noqa: BLE001
            log.warning("ocr.engine_failed", error=str(exc))
            return OCRResult(text="")

        text = "\n".join(b.text for b in blocks if b.text.strip())
        avg = (
            sum(b.confidence for b in blocks) / len(blocks)
            if blocks else 0.0
        )
        h, w = (processed.shape[:2]) if hasattr(processed, "shape") else (0, 0)
        return OCRResult(
            text=text,
            blocks=blocks,
            confidence_avg=avg,
            languages=self._languages,
            width=w,
            height=h,
        )

    def _run_engine(self, processed: Any) -> list[OCRBlock]:
        if self._engine is not None:
            return self._engine(processed)
        # Real Tesseract path.
        pytesseract = _import_pytesseract()
        data = pytesseract.image_to_data(
            processed,
            lang=self._languages,
            config=DEFAULT_TESSERACT_CONFIG,
            output_type=pytesseract.Output.DICT,
        )
        blocks: list[OCRBlock] = []
        n = len(data.get("text", []))
        for i in range(n):
            txt = (data["text"][i] or "").strip()
            if not txt:
                continue
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = 0.0
            if conf < 0:
                continue  # Tesseract uses -1 for "no confidence"
            try:
                bbox = (
                    int(data["left"][i]),
                    int(data["top"][i]),
                    int(data["width"][i]),
                    int(data["height"][i]),
                )
            except (KeyError, TypeError, ValueError):
                bbox = None
            blocks.append(OCRBlock(text=txt, confidence=conf, bbox=bbox))
        return blocks
