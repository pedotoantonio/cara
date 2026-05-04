"""BillWorkflow — PDF bolletta → reminder pagamento + spesa registrata.

Italian utility bills (Enel, A2A, Hera, Acea, TIM, Vodafone, Wind, …)
follow predictable shapes:

  - "Importo da pagare: € 87,30"
  - "Scadenza: 15/05/2026"
  - "Numero cliente:" / "Cliente:" / "Codice servizio:"

The workflow:

  1. Classify: PDF bytes + textual hints in the first page (keywords
     "scadenza" + "importo" + a known provider name) → matches with
     decent confidence.
  2. Extract: pypdf text extraction, then regex over the joined text
     for amount, due-date, provider, customer-id (audit only).
  3. Propose:
       - `add_task` with due_date = scadenza, title "Pagare bolletta X"
       - `add_expense` (category=utilities) on the day the user actually
         paid — but NOT today: future-dated bills sit in the task list
         until paid. We emit the expense action with `spent_on=None`
         and a flag the UI uses to ask "is it paid?" before committing.
  4. Execute: tasks_svc + budgets_svc adapters.

Keeps the same Workflow Protocol shape as ReceiptWorkflow / RecipeWorkflow
so the dispatcher loop in `cara/api/v1/workflows.py` walks them all
identically.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

import structlog

from cara.workflows.base import (
    ClassifyResult,
    ExecutionResult,
    ProposedAction,
    StructuredData,
    WorkflowInput,
)


log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Italian utility-bill markers
# ---------------------------------------------------------------------------


_BILL_KEYWORDS = (
    "importo da pagare",
    "totale da pagare",
    "scadenza",
    "data di scadenza",
    "entro il",
    "bolletta",
    "fattura",
    "numero cliente",
    "codice cliente",
    "codice servizio",
    "p.iva",
    "partita iva",
)


# Common providers — present-tense brand list, used for category +
# provider-name extraction.
_PROVIDERS = (
    ("enel", "Enel"),
    ("eni plenitude", "Eni Plenitude"),
    ("a2a", "A2A"),
    ("hera", "Hera"),
    ("acea", "Acea"),
    ("italgas", "Italgas"),
    ("snam", "Snam"),
    ("iren", "Iren"),
    ("edison", "Edison"),
    ("sorgenia", "Sorgenia"),
    ("tim ", "TIM"),
    ("telecom italia", "TIM"),
    ("vodafone", "Vodafone"),
    ("wind tre", "WindTre"),
    ("windtre", "WindTre"),
    ("fastweb", "Fastweb"),
    ("iliad", "Iliad"),
    ("sky italia", "Sky"),
    ("netflix", "Netflix"),
    ("amazon prime", "Amazon Prime"),
    ("disney+", "Disney+"),
)


_AMOUNT_RE = re.compile(
    # Non-greedy filler between the keyword and the digits — otherwise
    # "totale da pagare 105,00" greedy-eats "10" and parses as 5,00.
    r"(?:importo|totale|saldo|da\s+pagare)[\s\w:.€-]*?"
    r"(?:€\s*)?(\d{1,4})[,.](\d{2})",
    re.IGNORECASE,
)


# Fallback amount: any "€ X,YY" or "X,YY EUR" — used only when the
# specific "importo da pagare" pattern misses.
_FALLBACK_AMOUNT_RE = re.compile(
    r"€\s*(\d{1,4})[,.](\d{2})|(\d{1,4})[,.](\d{2})\s*(?:EUR|€)",
    re.IGNORECASE,
)


# Due-date forms: "scadenza 15/05/2026", "entro il 15-05-2026",
# "data di scadenza: 15.05.26".
_DUE_DATE_RE = re.compile(
    r"(?:scadenza|entro\s+il|data\s+di\s+scadenza|pagare\s+entro)"
    r"[\s:.\-]*"
    r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})",
    re.IGNORECASE,
)


# Generic ISO/EU date elsewhere in the doc (issue date, period covered).
_ANY_DATE_RE = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})\b")


# Customer / contract id — varies wildly. We don't try to parse it
# semantically; we just preserve the line for the UI to show.
_CUSTOMER_ID_RE = re.compile(
    r"(?:numero\s+cliente|codice\s+cliente|codice\s+servizio|cod\.\s*cliente)"
    r"[\s:.\-]*([A-Za-z0-9\-]{4,40})",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Parser — pure functions
# ---------------------------------------------------------------------------


def looks_like_bill(text: str) -> tuple[bool, float]:
    """Heuristic. Conservative — better to miss than to flag a non-bill."""
    if not text or len(text) < 60:
        return False, 0.0
    low = text.lower()
    score = 0.0
    for kw in _BILL_KEYWORDS:
        if kw in low:
            score += 0.12
    if any(p in low for p, _ in _PROVIDERS):
        score += 0.25
    if _AMOUNT_RE.search(text) or _DUE_DATE_RE.search(text):
        score += 0.3
    score = min(score, 1.0)
    return score >= 0.4, score


def parse_amount_cents(text: str) -> int | None:
    """Find 'importo da pagare …' first; fall back to any €/EUR amount."""
    m = _AMOUNT_RE.search(text)
    if m is None:
        m = _FALLBACK_AMOUNT_RE.search(text)
        if m is None:
            return None
    # _AMOUNT_RE has 2 groups; fallback can have 4 (alternation).
    nums = [g for g in m.groups() if g is not None]
    if len(nums) < 2:
        return None
    try:
        euros = int(nums[0])
        cents = int(nums[1])
    except ValueError:
        return None
    if euros > 5_000:                     # €5000 utility bill is implausible
        return None
    return euros * 100 + cents


def _safe_date(d: int, m: int, y: int) -> date | None:
    if y < 100:
        y += 2000
    if not (1 <= m <= 12 and 1 <= d <= 31 and 2000 <= y <= 2100):
        return None
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_due_date(text: str) -> date | None:
    m = _DUE_DATE_RE.search(text)
    if not m:
        return None
    d, mth, y = m.groups()
    return _safe_date(int(d), int(mth), int(y))


def parse_provider(text: str) -> str | None:
    low = text.lower()
    for needle, label in _PROVIDERS:
        if needle in low:
            return label
    return None


def parse_customer_id(text: str) -> str | None:
    m = _CUSTOMER_ID_RE.search(text)
    return m.group(1) if m else None


@dataclass
class ParsedBill:
    provider: str | None
    amount_cents: int | None
    due_date: date | None
    customer_id: str | None
    raw_text: str
    confidence: float


def parse_bill_text(text: str) -> ParsedBill:
    matched, confidence = looks_like_bill(text)
    return ParsedBill(
        provider=parse_provider(text),
        amount_cents=parse_amount_cents(text),
        due_date=parse_due_date(text),
        customer_id=parse_customer_id(text),
        raw_text=text,
        confidence=confidence if matched else 0.0,
    )


# ---------------------------------------------------------------------------
# Adapter signatures
# ---------------------------------------------------------------------------


# Sync (bytes) → text. Production binds to a thin pypdf wrapper.
PDFExtractFn = Callable[[bytes], str]

# Async (user_id, title, due_date) → Task-shaped row.
AddTaskFn = Callable[..., "Awaitable[Any]"]

# Async (user_id, amount_cents, category, vendor, spent_on?) → Expense.
AddExpenseFn = Callable[..., "Awaitable[Any]"]


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


@dataclass
class BillWorkflowConfig:
    classify_min_confidence: float = 0.40


class BillWorkflow:
    """PDF bolletta → reminder pagamento + spesa registrata.

    Conforms to the `Workflow` Protocol. Adapters injected at
    construction so unit tests can use fakes.
    """

    name: str = "bill"
    version: str = "0.1.0"

    def __init__(
        self,
        *,
        pdf_extract: PDFExtractFn | None = None,
        add_task: AddTaskFn | None = None,
        add_expense: AddExpenseFn | None = None,
        config: BillWorkflowConfig | None = None,
    ) -> None:
        self._pdf = pdf_extract
        self._add_task = add_task
        self._add_expense = add_expense
        self._cfg = config or BillWorkflowConfig()

    # ----------------------------------------------------------- 1. classify

    async def classify(self, inp: WorkflowInput) -> ClassifyResult:
        text: str | None = inp.get("pdf_text")
        if text is None:
            pdf_bytes: bytes | None = inp.get("pdf_bytes")
            if not pdf_bytes or self._pdf is None:
                return ClassifyResult(matches=False, reason="no_input_or_extractor")
            try:
                text = self._pdf(pdf_bytes)
            except Exception as exc:  # noqa: BLE001
                log.warning("bill.pdf_extract_failed", error=str(exc))
                return ClassifyResult(matches=False, reason=f"pdf_error:{exc}")

        matched, confidence = looks_like_bill(text or "")
        if not matched:
            return ClassifyResult(
                matches=False, confidence=confidence,
                reason=f"low_score:{confidence:.2f}",
            )
        return ClassifyResult(
            matches=True, confidence=confidence,
            reason="bill_keywords_detected",
            hints={"pdf_text": text},
        )

    # ----------------------------------------------------------- 2. extract

    async def extract(
        self, inp: WorkflowInput, hints: dict[str, Any],
    ) -> StructuredData:
        text = hints.get("pdf_text") or inp.get("pdf_text") or ""
        parsed = parse_bill_text(text)
        return StructuredData(
            kind=self.name,
            data={
                "user_id": inp.payload.get("user_id"),
                "provider": parsed.provider,
                "amount_cents": parsed.amount_cents,
                "due_date": parsed.due_date.isoformat() if parsed.due_date else None,
                "customer_id": parsed.customer_id,
                "category": "utilities",
            },
            confidence=parsed.confidence,
            raw_text=text[:4000],
        )

    # ----------------------------------------------------------- 3. propose

    async def propose(self, data: StructuredData) -> list[ProposedAction]:
        d = data.data
        user_id = d.get("user_id")
        if not user_id:
            return []

        actions: list[ProposedAction] = []
        provider = d.get("provider") or "fornitore"
        amount = d.get("amount_cents")
        due_iso = d.get("due_date")

        # Action 1 — reminder. Always emitted when there's a due date or
        # a recognisable provider.
        if due_iso or provider:
            amount_str = (
                f"€{amount/100:.2f}" if amount is not None else "importo non chiaro"
            )
            title = f"Pagare bolletta {provider} ({amount_str})"
            actions.append(ProposedAction(
                tool="add_task",
                args={
                    "user_id": user_id, "title": title,
                    "due_date": due_iso,
                },
                summary=(
                    f"Aggiungo un promemoria: {title}"
                    + (f", scadenza {due_iso}" if due_iso else "")
                ),
                reversible=True,
            ))

        # Action 2 — pre-staged expense. NOT executed automatically:
        # `spent_on=None` and the UI surfaces a "marca come pagata"
        # button. When the user confirms, the chat layer fills in
        # today's date and runs `add_expense` for real.
        if amount is not None:
            actions.append(ProposedAction(
                tool="add_expense_pending",
                args={
                    "user_id": user_id,
                    "amount_cents": amount,
                    "category": d.get("category", "utilities"),
                    "vendor": provider,
                    "due_date": due_iso,
                },
                summary=(
                    f"Quando paghi, registro €{amount/100:.2f} a {provider} "
                    "nel budget utilities."
                ),
                reversible=True,
            ))

        return actions

    # ----------------------------------------------------------- 4. execute

    async def execute(
        self, actions: "Iterable[ProposedAction]",  # noqa: F821
    ) -> list[ExecutionResult]:
        results: list[ExecutionResult] = []
        for action in actions:
            try:
                if action.tool == "add_task":
                    if self._add_task is None:
                        results.append(ExecutionResult.failure(
                            action, error="add_task adapter not configured",
                        ))
                        continue
                    args = action.args
                    due_iso = args.get("due_date")
                    due = date.fromisoformat(due_iso) if due_iso else None
                    task = await self._add_task(
                        user_id=args["user_id"],
                        title=args["title"],
                        due_date=due,
                    )
                    results.append(ExecutionResult.success(
                        action, output={"task_id": getattr(task, "id", None)},
                    ))

                elif action.tool == "add_expense_pending":
                    # NOT executed yet — the UI must explicitly confirm
                    # "marca come pagata" → at that point the chat layer
                    # calls `add_expense` directly with today's date.
                    # We surface this action as a structured "pending
                    # expense" record the UI tracks separately.
                    args = action.args
                    results.append(ExecutionResult.success(
                        action,
                        output={
                            "pending": True,
                            "amount_cents": args["amount_cents"],
                            "category": args["category"],
                            "vendor": args.get("vendor"),
                            "due_date": args.get("due_date"),
                        },
                    ))

                else:
                    results.append(ExecutionResult.failure(
                        action, error=f"unknown tool: {action.tool}",
                    ))
            except Exception as exc:  # noqa: BLE001
                log.warning("bill.execute.action_failed",
                            tool=action.tool, error=str(exc))
                results.append(ExecutionResult.failure(action, error=str(exc)))
        return results
