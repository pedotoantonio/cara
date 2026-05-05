"""RecipeWorkflow — URL / OCR text / typed message → ingredienti → shopping list.

Three input shapes share the same extract+propose+execute pipeline:

  - **URL** (link to a recipe page): trafilatura fetches + cleans, then
    `extract_ingredients` (already in `cara.services.recipe_chain`)
    pulls the bullet list.
  - **OCR text** (scanned cookbook page): same parser as above,
    skipping the network step.
  - **Typed text** ("metti gli ingredienti della carbonara"): falls
    back to the legacy `recipe_chain.run` which uses a CDA discover.

The propose stage emits one `add_shopping_item` ProposedAction per
extracted ingredient (capped at 30 to avoid pathological recipe pages).
The user confirms once and CARA writes the items.

Most of the heavy lifting (HTML parsing, ingredient cleaning) is
already implemented in `cara.services.recipe_chain` thanks to Step 64.
This workflow is the thin glue that:
  - exposes that logic via the standard Workflow Protocol,
  - lets unit tests inject fake fetch/extract callables,
  - adds OCR-text ingestion (cookbook photo case).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
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
# Heuristics
# ---------------------------------------------------------------------------


_URL_RE = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)


# Italian recipe-page keywords. We use these to score a piece of text:
# the more present, the higher the confidence it's a recipe.
_RECIPE_KEYWORDS = (
    "ingredienti",
    "preparazione",
    "procedimento",
    "ricetta",
    "ricette",
    "porzioni",
    "dosi per",
    "cottura",
    "tempo di",
    "difficoltà",
)


def looks_like_recipe(text: str) -> tuple[bool, float]:
    """Score `text` against recipe-page markers."""
    if not text or len(text) < 30:
        return False, 0.0
    low = text.lower()
    score = 0.0
    for kw in _RECIPE_KEYWORDS:
        if kw in low:
            score += 0.18
    score = min(score, 1.0)
    return score >= 0.30, score


def find_url(text: str) -> str | None:
    m = _URL_RE.search(text or "")
    return m.group(0) if m else None


# ---------------------------------------------------------------------------
# Adapter signatures
# ---------------------------------------------------------------------------


# Async URL → cleaned text (trafilatura wrapper). Production binds to
# `cara.cda.discovery.fetch_text` or similar.
FetchTextFn = Callable[[str], "Awaitable[str]"]

# Sync text → list of ingredient strings.
# Production binds to `cara.services.recipe_chain.extract_ingredients`.
ExtractIngredientsFn = Callable[[str], list[str]]

# Async (user_id, title) → ShoppingItem-like object. Production binds
# to `cara.services.shopping.create_item`.
AddShoppingFn = Callable[..., "Awaitable[Any]"]


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


@dataclass
class RecipeWorkflowConfig:
    max_ingredients: int = 30
    fetch_timeout_seconds: int = 8


class RecipeWorkflow:
    """URL / OCR text / typed message → ingredienti → shopping list."""

    name: str = "recipe"
    version: str = "0.1.0"

    def __init__(
        self,
        *,
        fetch_text: FetchTextFn | None = None,
        extract_ingredients: ExtractIngredientsFn | None = None,
        add_shopping: AddShoppingFn | None = None,
        config: RecipeWorkflowConfig | None = None,
    ) -> None:
        self._fetch = fetch_text
        self._extract = extract_ingredients
        self._add_shopping = add_shopping
        self._cfg = config or RecipeWorkflowConfig()

    # ----------------------------------------------------------- 1. classify

    async def classify(self, inp: WorkflowInput) -> ClassifyResult:
        """Detect a recipe input shape:
          - inline URL → matches with high confidence
          - OCR text scoring above threshold → matches
          - typed message with "ricetta" keyword → falls through
        """
        # 1) URL — short-circuit.
        url: str | None = inp.get("url") or find_url(inp.get("text") or "")
        if url:
            return ClassifyResult(
                matches=True, confidence=0.85,
                reason="url_detected",
                hints={"url": url},
            )

        # 2) Inline text or OCR text.
        text: str = (
            inp.get("text")
            or inp.get("ocr_text")
            or ""
        )
        if not text:
            return ClassifyResult(matches=False, reason="no_text_no_url")

        matched, score = looks_like_recipe(text)
        if matched:
            return ClassifyResult(
                matches=True, confidence=score,
                reason="recipe_keywords",
                hints={"text": text},
            )
        return ClassifyResult(
            matches=False, confidence=score,
            reason=f"low_score:{score:.2f}",
        )

    # ----------------------------------------------------------- 2. extract

    async def extract(
        self, inp: WorkflowInput, hints: dict[str, Any],
    ) -> StructuredData:
        url = hints.get("url")
        text = hints.get("text") or inp.get("text") or inp.get("ocr_text") or ""
        source: str = "text"

        if url and self._fetch is not None:
            try:
                text = await self._fetch(url)
                source = "url"
            except Exception as exc:  # noqa: BLE001
                log.warning("recipe.fetch_failed", url=url, error=str(exc))
                # Fall through to whatever inline text we have (often empty).

        ingredients: list[str] = []
        if self._extract is not None and text:
            try:
                ingredients = self._extract(text)
            except Exception as exc:  # noqa: BLE001
                log.warning("recipe.extract_failed", error=str(exc))

        # Sanity cap.
        ingredients = [
            i.strip() for i in ingredients
            if i and isinstance(i, str)
        ][: self._cfg.max_ingredients]

        return StructuredData(
            kind=self.name,
            data={
                "user_id": inp.payload.get("user_id"),
                "url": url,
                "source": source,
                "ingredients": ingredients,
                "ingredients_count": len(ingredients),
            },
            confidence=0.85 if ingredients else 0.0,
            raw_text=text[:4000] if text else "",
        )

    # ----------------------------------------------------------- 3. propose

    async def propose(self, data: StructuredData) -> list[ProposedAction]:
        d = data.data
        user_id = d.get("user_id")
        ingredients: list[str] = d.get("ingredients") or []
        if not user_id or not ingredients:
            return []

        # One bulk action — UI shows the full list and the user confirms once.
        return [ProposedAction(
            tool="bulk_add_shopping",
            args={"user_id": user_id, "items": ingredients},
            summary=(
                f"Aggiungo {len(ingredients)} ingredienti alla spesa: "
                + ", ".join(ingredients[:5])
                + ("…" if len(ingredients) > 5 else "")
            ),
            reversible=True,
        )]

    # ----------------------------------------------------------- 4. execute

    async def execute(
        self, actions: "Iterable[ProposedAction]",  # noqa: F821
    ) -> list[ExecutionResult]:
        results: list[ExecutionResult] = []
        for action in actions:
            if action.tool != "bulk_add_shopping":
                results.append(ExecutionResult.failure(
                    action, error=f"unknown tool: {action.tool}",
                ))
                continue
            if self._add_shopping is None:
                results.append(ExecutionResult.failure(
                    action, error="add_shopping adapter not configured",
                ))
                continue

            args = action.args
            user_id = args["user_id"]
            items: list[str] = list(args.get("items") or [])
            added_ids: list[Any] = []
            errors: list[str] = []
            for title in items:
                try:
                    row = await self._add_shopping(user_id=user_id, title=title)
                    added_ids.append(getattr(row, "id", None))
                except Exception as exc:  # noqa: BLE001
                    log.warning("recipe.add_shopping_failed",
                                title=title, error=str(exc))
                    errors.append(f"{title}: {exc}")

            ok = len(added_ids) > 0
            output: dict[str, Any] = {
                "added_count": len(added_ids),
                "added_ids": added_ids,
                "total_requested": len(items),
            }
            if errors:
                output["errors"] = errors[:10]
            if ok:
                results.append(ExecutionResult.success(action, output=output))
            else:
                results.append(ExecutionResult.failure(
                    action, error="no items added",
                ))
        return results
