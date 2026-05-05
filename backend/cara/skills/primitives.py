"""Built-in primitives for the Skill Factory.

This module is imported at app startup to populate the registry. New primitives
go here (or in dedicated submodules that are imported from here)."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cara.cda import CdaError, DiscoverRequest, discover as cda_discover
from cara.services import shopping as shopping_svc
from cara.services.recipe_chain import extract_ingredients
from cara.skills.registry import primitive

log = structlog.get_logger(__name__)


@primitive(
    name="discover",
    description=(
        "Cerca su internet contenuti del tipo richiesto e restituisce il primo "
        "risultato verificato (URL, titolo, dominio sorgente, testo estratto se "
        "articolo)."
    ),
    args_schema={"query": "string", "kind": "string"},
    returns_schema={
        "url": "string",
        "title": "string",
        "source_domain": "string",
        "text": "string",
        "metadata": "dict",
    },
    needs_session=True,
    needs_user_id=True,
)
async def _prim_discover(
    session: AsyncSession, user_id: int, query: str, kind: str = "article"
) -> dict[str, Any]:
    try:
        result = await cda_discover(
            session,
            DiscoverRequest(
                user_id=user_id, raw_query=query, content_type=kind, modifiers={}  # type: ignore[arg-type]
            ),
        )
    except CdaError as exc:
        raise RuntimeError(f"discover failed: {exc}") from exc
    return {
        "url": result.url,
        "title": result.title,
        "source_domain": result.source_domain,
        "text": str(result.metadata.get("text") or ""),
        "metadata": result.metadata,
    }


@primitive(
    name="extract_recipe_ingredients",
    description=(
        "Dato un testo di ricetta in italiano, ritorna la lista pulita degli "
        "ingredienti (regex deterministica sulla sezione 'Ingredienti', niente "
        "LLM, niente quantità). Funziona meglio su pagine tipo GialloZafferano."
    ),
    args_schema={"text": "string", "max_items": "int"},
    returns_schema={"items": "list[str]", "count": "int"},
)
async def _prim_extract_ingredients(text: str, max_items: int = 30) -> dict[str, Any]:
    items = extract_ingredients(text or "", max_items=int(max_items))
    return {"items": items, "count": len(items)}


@primitive(
    name="add_shopping_bulk",
    description=(
        "Aggiunge una lista di articoli alla lista della spesa dell'utente "
        "in una sola transazione. Ritorna count e preview dei primi 8 titoli."
    ),
    args_schema={"titles": "list[str]"},
    returns_schema={"count": "int", "list": "string", "preview": "string"},
    needs_session=True,
    needs_user_id=True,
)
async def _prim_add_shopping_bulk(
    session: AsyncSession, user_id: int, titles: list[str]
) -> dict[str, Any]:
    if not titles:
        return {"count": 0, "list": "", "preview": ""}
    added: list[str] = []
    for t in titles:
        try:
            await shopping_svc.create_item(session, user_id=user_id, title=str(t))
            added.append(str(t))
        except Exception as exc:  # noqa: BLE001
            log.warning("primitive.add_shopping_bulk.item_failed", title=t, error=str(exc))
    preview = ", ".join(added[:8])
    if len(added) > 8:
        preview = f"{preview} e altri {len(added) - 8}"
    return {"count": len(added), "list": ", ".join(added), "preview": preview}
