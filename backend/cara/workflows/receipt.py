"""ReceiptWorkflow — foto di scontrino → items off shopping list + expense logged.

Pipeline (Italian receipts, store-agnostic):

    image bytes → classify (size + density + IT keywords)
                → extract (OCR Tesseract + parse vendor/date/items/totale)
                → propose (fuzzy match items vs open shopping list,
                           categorize for budget, return ProposedActions)
                → execute (per-action call to shopping_svc.update_item +
                           budgets_svc.add_expense)

The classifier is intentionally permissive — better to mis-classify a
random photo as a receipt and let the user dismiss it than to silently
drop a receipt because the OCR confidence was 0.7. The propose stage
puts everything behind a confirm gate by default; auto-confirm kicks
in after 3 successful confirmations of the same shape (Step 3.8).

Tested in unit tests via injected fakes — neither Tesseract nor the
DB are required at import time. Production wiring binds:
  - cara.ai.ocr.OCRService (real Tesseract)
  - cara.services.shopping (real DB)
  - cara.services.budgets (real DB + Expense table)
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import structlog
from rapidfuzz import fuzz

from cara.workflows.base import (
    ClassifyResult,
    ExecutionResult,
    ProposedAction,
    StructuredData,
    WorkflowInput,
)


log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Receipt-text patterns (Italian)
# ---------------------------------------------------------------------------


# Common keywords that strongly suggest "this is a receipt".
_KEYWORDS_RECEIPT = (
    "totale", "totale e", "totale eur", "subtotale", "scontrino",
    "iva", "contanti", "carta", "resto", "pos", "bancomat",
    "documento commerciale", "n.scontrino", "n. scontrino",
)

# Italian receipt amount: "1,50" or "12,30" with comma decimal.
# Optional € sign. Captures the digits.
_AMOUNT_RE = re.compile(
    r"(?<![A-Za-z\d])(?:€\s*)?(\d{1,4})[,.](\d{2})(?!\d)",
)

# "Totale" line: tries to capture the final total. Various retailers
# write it differently, so we accept several forms.
_TOTAL_LINE_RE = re.compile(
    r"\b(?:totale|tot\.|tot\b)[\s.\-:eEuUrR]*\s*€?\s*(\d{1,4}[,.]\d{2})",
    re.IGNORECASE,
)

# Date in dd/mm/yyyy, dd-mm-yyyy, dd.mm.yyyy.
_DATE_RE = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})\b")

# Vendor: usually the first non-empty line of the OCR. We strip it of
# obvious noise (numbers, all-uppercase short words like "VIA").
_VENDOR_NOISE_RE = re.compile(r"^[\d\W]+$")


# Lines that are clearly NOT items (footer, totals section, receipt
# metadata). The item parser skips them.
_NOT_ITEM_PATTERNS = (
    re.compile(r"^\s*(?:totale|subtotale|tot\.?|iva|sconto)\b", re.IGNORECASE),
    re.compile(r"^\s*(?:contanti|carta|resto|pos|bancomat|documento)", re.IGNORECASE),
    re.compile(r"^\s*[€\s\d.,]+\s*$"),  # only digits/punct/euro
    re.compile(r"\d{2}[/.\-]\d{2}[/.\-]\d{2,4}"),  # date lines
)


# Heuristic category hints from vendor / item names.
_CATEGORY_HINTS = (
    (re.compile(r"\b(?:conad|coop|esselunga|carrefour|lidl|md|in's|despar|pam|simply|crai)\b", re.I), "groceries"),
    (re.compile(r"\b(?:farmacia|parafarmacia)\b", re.I), "health"),
    (re.compile(r"\b(?:ip|q8|eni|tamoil|esso|agip|repsol|carburante|benzina)\b", re.I), "transport"),
    (re.compile(r"\b(?:enel|a2a|hera|acea|wind|tim|vodafone|fastweb|tre)\b", re.I), "utilities"),
)


# ---------------------------------------------------------------------------
# Parser — pure functions over OCR text
# ---------------------------------------------------------------------------


@dataclass
class ReceiptItem:
    """One line item parsed from the receipt."""
    name: str
    amount_cents: int
    qty: float | None = None     # parsed when "2 x 1,50" pattern visible


@dataclass
class ParsedReceipt:
    """Output of the OCR-text parser. Self-documenting for the UI."""
    vendor: str | None
    date: date | None
    items: list[ReceiptItem]
    total_cents: int | None
    raw_text: str
    confidence: float            # 0..1, our own heuristic


def looks_like_receipt(text: str) -> tuple[bool, float]:
    """True + confidence score if `text` reads like a receipt.

    Conservative: even a low-confidence guess passes through to the
    propose stage so the user can decide.
    """
    if not text or len(text) < 20:
        return False, 0.0
    lower = text.lower()
    score = 0.0
    for kw in _KEYWORDS_RECEIPT:
        if kw in lower:
            score += 0.15
    if _TOTAL_LINE_RE.search(text):
        score += 0.3
    if _DATE_RE.search(text):
        score += 0.1
    # Caps at 1.0.
    score = min(score, 1.0)
    return score >= 0.25, score


def parse_total(text: str) -> int | None:
    """Find the receipt total and return amount in cents."""
    matches = _TOTAL_LINE_RE.findall(text)
    if not matches:
        return None
    # Last total line wins — many receipts also have a "subtotale" earlier.
    raw = matches[-1].replace(".", ",")
    try:
        euros, cents = raw.split(",")
        return int(euros) * 100 + int(cents)
    except ValueError:
        return None


def parse_date(text: str) -> date | None:
    """Try to parse the first date-looking match, prefer dd/mm/yyyy."""
    m = _DATE_RE.search(text)
    if not m:
        return None
    d, mth, y = m.groups()
    try:
        di = int(d)
        mi = int(mth)
        yi = int(y)
        if yi < 100:                    # "26" → 2026
            yi += 2000
        if not (1 <= mi <= 12 and 1 <= di <= 31 and 2000 <= yi <= 2100):
            return None
        return date(yi, mi, di)
    except ValueError:
        return None


def parse_vendor(text: str) -> str | None:
    """Heuristic: the first 'meaningful' non-empty line of the receipt."""
    for line in text.splitlines():
        clean = line.strip()
        if not clean or len(clean) < 3:
            continue
        if _VENDOR_NOISE_RE.match(clean):
            continue
        # Skip if the line is all-uppercase and all-numeric / all-punct.
        if not any(c.isalpha() for c in clean):
            continue
        return clean[:200]
    return None


def parse_items(text: str) -> list[ReceiptItem]:
    """Extract one ReceiptItem per non-noise line containing an amount.

    Handles common Italian receipt shapes:
      "PANE INTEGRALE        1,80"
      "LATTE 1L     1,29 EUR"
      "MELE GOLDEN  1.234 KG  3,50"
    """
    items: list[ReceiptItem] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or len(line) < 5:
            continue
        if any(p.search(line) for p in _NOT_ITEM_PATTERNS):
            continue
        m = _AMOUNT_RE.search(line)
        if m is None:
            continue
        amount_cents = int(m.group(1)) * 100 + int(m.group(2))
        if amount_cents <= 0 or amount_cents > 200_000:
            # > 2000€ on one line is almost certainly an OCR error.
            continue
        # Item name = the line minus the amount substring.
        name = (line[:m.start()] + line[m.end():]).strip(" .-€\t")
        if not name or len(name) < 2:
            continue
        # Cap extremely long names (OCR can fuse two columns).
        name = name[:120]
        items.append(ReceiptItem(name=name, amount_cents=amount_cents))
    return items


def infer_category(vendor: str | None, items: list[ReceiptItem]) -> str:
    """Pick the best canonical category for the budget bucket."""
    haystack = ((vendor or "") + " " + " ".join(i.name for i in items)).lower()
    for pattern, cat in _CATEGORY_HINTS:
        if pattern.search(haystack):
            return cat
    return "groceries"   # most receipts a family handles are groceries


def parse_receipt_text(text: str) -> ParsedReceipt:
    """Run all parsers on `text` and bundle the result."""
    matched, confidence = looks_like_receipt(text)
    return ParsedReceipt(
        vendor=parse_vendor(text),
        date=parse_date(text),
        items=parse_items(text),
        total_cents=parse_total(text),
        raw_text=text,
        confidence=confidence if matched else 0.0,
    )


# ---------------------------------------------------------------------------
# Workflow class
# ---------------------------------------------------------------------------


# Adapter callables passed into ReceiptWorkflow at construction time so
# unit tests can inject fakes. Each signature mirrors what the
# corresponding cara.services / cara.ai module already exposes.
OCRCallable = Callable[[bytes], "Awaitable[Any]"]    # returns OCRResult-shaped
ShoppingListFn = Callable[[int], "Awaitable[list[Any]]"]
ShoppingMarkBoughtFn = Callable[[int, int], "Awaitable[bool]"]
AddExpenseFn = Callable[..., "Awaitable[Any]"]


@dataclass
class ReceiptWorkflowConfig:
    """Tunable thresholds — exposed so the admin UI can edit them."""
    classify_min_confidence: float = 0.25
    fuzzy_match_threshold: int = 78         # rapidfuzz token_set_ratio score 0..100
    auto_confirm_after_n_confirms: int = 3  # Step 3.8 wiring


class ReceiptWorkflow:
    """Concrete Workflow for "foto scontrino → spesa updated + budget logged".

    Conforms to `cara.workflows.base.Workflow` Protocol.

    Construct with adapter callables so unit tests can inject fakes:

        wf = ReceiptWorkflow(
            ocr_extract=fake_ocr,
            shopping_list=fake_shopping_list,
            shopping_mark_bought=fake_mark_bought,
            add_expense=fake_add_expense,
        )
    """

    name: str = "receipt"
    version: str = "0.1.0"

    def __init__(
        self,
        *,
        ocr_extract: OCRCallable | None = None,
        shopping_list: ShoppingListFn | None = None,
        shopping_mark_bought: ShoppingMarkBoughtFn | None = None,
        add_expense: AddExpenseFn | None = None,
        config: ReceiptWorkflowConfig | None = None,
    ) -> None:
        self._ocr = ocr_extract
        self._shopping_list = shopping_list
        self._shopping_mark_bought = shopping_mark_bought
        self._add_expense = add_expense
        self._cfg = config or ReceiptWorkflowConfig()

    # ----------------------------------------------------------- 1. classify

    async def classify(self, inp: WorkflowInput) -> ClassifyResult:
        """Quick yes/no on whether this looks like a receipt.

        Two paths:
        - If the input already has OCR text in `payload["ocr_text"]`
          (cached from a previous step), classify on that directly.
        - Otherwise run the OCR adapter on `payload["image_bytes"]`.

        The OCR adapter call is the only expensive operation; we cache
        its result in `hints` so `extract()` can re-use it.
        """
        text: str | None = inp.get("ocr_text")
        if text is None:
            image_bytes: bytes | None = inp.get("image_bytes")
            if not image_bytes or self._ocr is None:
                return ClassifyResult(matches=False, reason="no_input_or_ocr")
            try:
                ocr_res = await self._ocr(image_bytes)
            except Exception as exc:  # noqa: BLE001
                log.warning("receipt.ocr_failed", error=str(exc))
                return ClassifyResult(matches=False, reason=f"ocr_error:{exc}")
            text = getattr(ocr_res, "text", "") or ""

        matched, confidence = looks_like_receipt(text)
        if not matched:
            return ClassifyResult(
                matches=False,
                reason=f"low_score:{confidence:.2f}",
                confidence=confidence,
            )
        return ClassifyResult(
            matches=True,
            confidence=confidence,
            reason="receipt_keywords_detected",
            hints={"ocr_text": text},
        )

    # ----------------------------------------------------------- 2. extract

    async def extract(
        self, inp: WorkflowInput, hints: dict[str, Any],
    ) -> StructuredData:
        text = hints.get("ocr_text") or inp.get("ocr_text") or ""
        parsed = parse_receipt_text(text)
        category = infer_category(parsed.vendor, parsed.items)
        return StructuredData(
            kind=self.name,
            data={
                "vendor": parsed.vendor,
                "date": parsed.date.isoformat() if parsed.date else None,
                "items": [
                    {"name": it.name, "amount_cents": it.amount_cents}
                    for it in parsed.items
                ],
                "total_cents": parsed.total_cents,
                "category": category,
            },
            confidence=parsed.confidence,
            raw_text=text[:4000],
        )

    # ----------------------------------------------------------- 3. propose

    async def propose(self, data: StructuredData) -> list[ProposedAction]:
        """Build the action list the user reviews + confirms.

        Two action families:
          1. complete_shopping_item — for each receipt item that fuzzy-
             matches an open shopping_list entry above threshold.
          2. add_expense — one row, total of the receipt, categorised.
        """
        actions: list[ProposedAction] = []
        d = data.data
        receipt_items = d.get("items") or []
        total_cents = d.get("total_cents")
        category = d.get("category", "groceries")
        vendor = d.get("vendor") or ""
        date_iso = d.get("date")

        # Action 1: shopping-list matches
        user_id: int = d.get("user_id", 0)
        if user_id and self._shopping_list is not None and receipt_items:
            try:
                open_items = await self._shopping_list(user_id)
            except Exception as exc:  # noqa: BLE001
                log.warning("receipt.shopping_list_failed", error=str(exc))
                open_items = []

            for item in receipt_items:
                best = self._best_shopping_match(item["name"], open_items)
                if best is None:
                    continue
                actions.append(ProposedAction(
                    tool="complete_shopping_item",
                    args={
                        "user_id": user_id,
                        "item_id": best["id"],
                        "matched_name": best["title"],
                        "receipt_name": item["name"],
                        "match_score": best["score"],
                    },
                    summary=(
                        f"Tolgo dalla spesa «{best['title']}» "
                        f"(in scontrino: «{item['name']}»)."
                    ),
                    reversible=True,
                ))

        # Action 2: expense logging
        if total_cents and total_cents > 0:
            actions.append(ProposedAction(
                tool="add_expense",
                args={
                    "user_id": user_id,
                    "amount_cents": total_cents,
                    "category": category,
                    "vendor": vendor,
                    "spent_on": date_iso,
                    "items_count": len(receipt_items),
                },
                summary=(
                    f"Registro nel budget: €{total_cents/100:.2f} "
                    f"a {vendor or 'venditore'} ({category})."
                ),
                reversible=True,
            ))

        return actions

    def _best_shopping_match(
        self, receipt_name: str, open_items: list[Any],
    ) -> dict[str, Any] | None:
        """Pick the single best fuzzy match in `open_items`, or None."""
        best_score = -1
        best_item: dict[str, Any] | None = None
        rn = receipt_name.lower()
        for entry in open_items:
            title = getattr(entry, "title", None) or entry.get("title", "")  # tolerant
            if not title:
                continue
            score = fuzz.token_set_ratio(rn, title.lower())
            if score >= self._cfg.fuzzy_match_threshold and score > best_score:
                best_score = score
                best_item = {
                    "id": getattr(entry, "id", None) or entry.get("id"),
                    "title": title,
                    "score": int(score),
                }
        return best_item

    # ----------------------------------------------------------- 4. execute

    async def execute(
        self, actions: "Iterable[ProposedAction]",  # noqa: F821
    ) -> list[ExecutionResult]:
        results: list[ExecutionResult] = []
        for action in actions:
            try:
                if action.tool == "complete_shopping_item":
                    if self._shopping_mark_bought is None:
                        results.append(ExecutionResult.failure(
                            action, error="shopping_mark_bought adapter not configured",
                        ))
                        continue
                    args = action.args
                    ok = await self._shopping_mark_bought(
                        args["user_id"], args["item_id"],
                    )
                    if ok:
                        results.append(ExecutionResult.success(
                            action, output={"matched": args.get("matched_name")},
                        ))
                    else:
                        results.append(ExecutionResult.failure(
                            action, error="item not found / already bought",
                        ))
                elif action.tool == "add_expense":
                    if self._add_expense is None:
                        results.append(ExecutionResult.failure(
                            action, error="add_expense adapter not configured",
                        ))
                        continue
                    args = action.args
                    spent_iso = args.get("spent_on")
                    spent_on = (
                        date.fromisoformat(spent_iso) if spent_iso else date.today()
                    )
                    expense = await self._add_expense(
                        user_id=args.get("user_id"),
                        spent_on=spent_on,
                        amount_cents=args["amount_cents"],
                        category=args["category"],
                        vendor=args.get("vendor"),
                    )
                    results.append(ExecutionResult.success(
                        action, output={"expense_id": getattr(expense, "id", None)},
                    ))
                else:
                    results.append(ExecutionResult.failure(
                        action, error=f"unknown tool: {action.tool}",
                    ))
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "receipt.execute.action_failed",
                    tool=action.tool, error=str(exc),
                )
                results.append(ExecutionResult.failure(
                    action, error=str(exc),
                ))
        return results
