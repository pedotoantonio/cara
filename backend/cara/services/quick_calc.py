"""Deterministic math/date/time intercept (Step "quick wins" — May 2026).

The 1.5B Qwen on RK3588 is unreliable at arithmetic and date math. Routing
those queries to a Python evaluator before the LLM ever sees them removes
a class of embarrassing errors ("6 per 7 = 21") at zero cost.

Three families handled:

1. **Arithmetic**: `\d+ [+\-×*x:/] \d+`, multi-operand, parenthesised, with
   Italian operator words (`più`, `meno`, `per`, `diviso`, `quanto fa`).
   Internal evaluator is `_safe_eval` (AST-walker, only `BinOp` + `Num` +
   `UnaryOp`); no `eval()`, no shell, no surface for injection.

2. **Time queries**: "che ore sono", "che ora è", with optional timezone
   keyword. Returns `HH:MM`.

3. **Date queries**: "che giorno è oggi", "che data è", "in che mese siamo",
   "quanti giorni mancano a [data | Natale | Capodanno]".

If a pattern matches AND the parser succeeds, we return a one-line Italian
answer. If parsing fails on a strong match (e.g. "3+5÷0"), we still return
a polite fallback so the LLM doesn't have to invent a number.

Pure functions, no side effects, no I/O — easily unit-testable.
"""

from __future__ import annotations

import ast
import operator
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo


# ---------------------------------------------------------------------------
# Italian month/day names (mirrors `_chat_prompt.py` to avoid the import cycle)
# ---------------------------------------------------------------------------

_WEEKDAYS_IT = [
    "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica",
]
_MONTHS_IT = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]


# ---------------------------------------------------------------------------
# Safe arithmetic evaluator
# ---------------------------------------------------------------------------

_OPS_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_OPS_UNARY = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _safe_eval(expr: str) -> float:
    """Evaluate a numeric expression. Raises ValueError on invalid input.

    Supports +, -, *, /, //, %, **, parentheses, unary +/-. Anything else
    (names, calls, attributes) raises immediately.
    """
    tree = ast.parse(expr, mode="eval")

    def _walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _walk(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, int | float) and not isinstance(node.value, bool):
                return float(node.value)
            raise ValueError(f"non-numeric constant: {node.value!r}")
        if isinstance(node, ast.UnaryOp):
            op = _OPS_UNARY.get(type(node.op))
            if op is None:
                raise ValueError(f"unsupported unary op: {type(node.op).__name__}")
            return op(_walk(node.operand))
        if isinstance(node, ast.BinOp):
            op = _OPS_BIN.get(type(node.op))
            if op is None:
                raise ValueError(f"unsupported binop: {type(node.op).__name__}")
            return op(_walk(node.left), _walk(node.right))
        raise ValueError(f"unsupported AST node: {type(node).__name__}")

    return _walk(tree)


# ---------------------------------------------------------------------------
# Italian → ASCII operator normalisation
# ---------------------------------------------------------------------------

_WORD_OPS = [
    (re.compile(r"\b(?:più|piu)\b", re.IGNORECASE), " + "),
    (re.compile(r"\bmeno\b", re.IGNORECASE), " - "),
    (re.compile(r"\b(?:per|moltiplicato\s+per)\b", re.IGNORECASE), " * "),
    (re.compile(r"\b(?:diviso|fratto|su)\b", re.IGNORECASE), " / "),
    (re.compile(r"\bal\s+quadrato\b", re.IGNORECASE), " ** 2"),
    (re.compile(r"\bal\s+cubo\b", re.IGNORECASE), " ** 3"),
    (re.compile(r"×"), "*"),
    (re.compile(r"x", re.IGNORECASE), "*"),  # only between digits — guarded below
    (re.compile(r"÷"), "/"),
    (re.compile(r","), "."),  # decimal comma → dot
]


def _normalise_for_eval(s: str) -> str:
    """Map Italian arithmetic words and unicode operators to AST-friendly chars."""
    out = s.strip()
    # Strip off final punctuation/question marks.
    out = re.sub(r"[?!.;:]+$", "", out)
    # "x" → "*" only when surrounded by digits (so we don't mangle "X anni").
    out = re.sub(r"(\d)\s*[xX]\s*(\d)", r"\1*\2", out)
    for pat, repl in _WORD_OPS:
        if pat.pattern == "x":
            continue  # handled above
        out = pat.sub(repl, out)
    # Collapse repeated whitespace.
    out = re.sub(r"\s+", " ", out).strip()
    return out


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Strong-arithmetic markers. If one of these appears AND the rest of the
# query reduces cleanly to an expression, we treat it as a calc.
_CALC_MARKERS = re.compile(
    r"\b(?:quanto\s+fa|quanto\s+è|quanto\s+e|calcola|risolvi|fa)\b",
    re.IGNORECASE,
)

# A bare expression like "3+5" or "12 * 4 / 2" with no surrounding prose.
_BARE_EXPR = re.compile(
    r"^\s*[-+]?\s*\d[\d\s+\-*/×÷x.,()]*\d\s*[?!.]?\s*$"
)

# Time queries.
_RE_TIME = re.compile(
    r"\b(?:che\s+ore?\s+sono|che\s+ora\s+(?:è|e)|"
    r"mi\s+dici\s+l['\s]?ora|che\s+ora\s+fa|adesso\s+(?:che\s+)?ore?)\b",
    re.IGNORECASE,
)

# Date queries.
_RE_DATE_TODAY = re.compile(
    r"\b(?:che\s+giorno\s+(?:è|e)\s+oggi|"
    r"che\s+data\s+(?:è|e)\s+oggi|"
    r"oggi\s+(?:che\s+giorno|che\s+data|quanto\s+ne\s+abbiamo)|"
    r"in\s+che\s+(?:giorno|data)\s+siamo)\b",
    re.IGNORECASE,
)

_RE_DATE_TOMORROW = re.compile(
    r"\b(?:che\s+giorno\s+(?:è|e|sarà)\s+domani|"
    r"che\s+data\s+(?:è|e|sarà)\s+domani|"
    r"domani\s+che\s+(?:giorno|data))\b",
    re.IGNORECASE,
)

_RE_DATE_MONTH = re.compile(
    r"\bin\s+che\s+mese\s+siamo\b|\bche\s+mese\s+(?:è|e)\b",
    re.IGNORECASE,
)

_RE_DATE_YEAR = re.compile(
    r"\bin\s+che\s+anno\s+siamo\b|\bche\s+anno\s+(?:è|e)\b",
    re.IGNORECASE,
)

_RE_DAYS_TO_XMAS = re.compile(
    r"\bquanti?\s+giorni?\s+(?:mancan[oa]|ci\s+(?:son[eo])?|mi)\s*"
    r"(?:a|al|all['\s])?\s*natale\b|"
    r"\b(?:quanto\s+manca|tra\s+quanto)\s+(?:a\s+|al\s+|per\s+|è\s+)?natale\b",
    re.IGNORECASE,
)

_RE_DAYS_TO_NEWYEAR = re.compile(
    r"\bquanti?\s+giorni?\s+(?:mancan[oa]|ci\s+(?:son[eo])?|mi)\s*"
    r"(?:a|al|all['\s])?\s*capodanno\b|"
    r"\b(?:quanto\s+manca|tra\s+quanto)\s+(?:a\s+|al\s+|per\s+|è\s+)?capodanno\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def try_calc(text: str) -> str | None:
    """Try to answer `text` from arithmetic / date / time intercepts.

    Returns an Italian one-liner if the query matches, else None.
    Never raises; on internal error returns None so the caller can fall
    through to the LLM tier.
    """
    if not text:
        return None
    q = text.strip()
    if not q:
        return None

    # ----- time -----
    if _RE_TIME.search(q):
        now = datetime.now(ZoneInfo("Europe/Rome"))
        return f"Sono le {now.hour:02d}:{now.minute:02d}."

    # ----- date / today -----
    if _RE_DATE_TODAY.search(q):
        now = datetime.now(ZoneInfo("Europe/Rome"))
        wd = _WEEKDAYS_IT[now.weekday()]
        m = _MONTHS_IT[now.month - 1]
        return f"Oggi è {wd} {now.day} {m} {now.year}."

    # ----- date / tomorrow -----
    if _RE_DATE_TOMORROW.search(q):
        from datetime import timedelta
        tomorrow = datetime.now(ZoneInfo("Europe/Rome")).date() + timedelta(days=1)
        wd = _WEEKDAYS_IT[tomorrow.weekday()]
        m = _MONTHS_IT[tomorrow.month - 1]
        return f"Domani è {wd} {tomorrow.day} {m} {tomorrow.year}."

    if _RE_DATE_MONTH.search(q):
        now = datetime.now(ZoneInfo("Europe/Rome"))
        return f"Siamo a {_MONTHS_IT[now.month - 1]}."

    if _RE_DATE_YEAR.search(q):
        now = datetime.now(ZoneInfo("Europe/Rome"))
        return f"Siamo nel {now.year}."

    if _RE_DAYS_TO_XMAS.search(q):
        return _days_to_target_str(month=12, day=25, label="al prossimo Natale")

    if _RE_DAYS_TO_NEWYEAR.search(q):
        return _days_to_target_str(month=1, day=1, label="al prossimo Capodanno")

    # ----- arithmetic -----
    answer = _try_arithmetic(q)
    if answer is not None:
        return answer

    return None


def _days_to_target_str(*, month: int, day: int, label: str) -> str:
    today = datetime.now(ZoneInfo("Europe/Rome")).date()
    target_year = today.year if today <= date(today.year, month, day) else today.year + 1
    diff = (date(target_year, month, day) - today).days
    if diff == 0:
        return f"È oggi! ({label.replace('al prossimo ', '')})"
    if diff == 1:
        return f"Manca 1 giorno {label}."
    return f"Mancano {diff} giorni {label}."


def _try_arithmetic(q: str) -> str | None:
    """Attempt to parse `q` as an arithmetic expression. Return formatted
    answer or None."""
    has_marker = _CALC_MARKERS.search(q) is not None
    is_bare = _BARE_EXPR.match(q) is not None
    if not (has_marker or is_bare):
        return None

    # Strip leading marker phrase ("quanto fa…", "calcola…").
    body = _CALC_MARKERS.sub("", q).strip()
    body = _normalise_for_eval(body)

    # Body must contain at least one digit and one operator after normalisation.
    if not re.search(r"\d", body):
        return None
    if not re.search(r"[+\-*/%()]|\*\*", body):
        return None
    # Reject anything that would let `ast.parse` accept a name.
    if re.search(r"[a-zA-Z]", body):
        return None

    try:
        result = _safe_eval(body)
    except (SyntaxError, ValueError, ZeroDivisionError, RecursionError):
        return None

    return _format_number(result)


def _format_number(n: float) -> str:
    """Render `n` in Italian style (comma decimals, no trailing zeros)."""
    if n == int(n) and abs(n) < 1e15:
        return f"{int(n)}"
    # Up to 4 decimals, strip trailing zeros, swap dot → comma.
    s = f"{n:.4f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")
