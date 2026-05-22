"""MCP server con FastMCP. Espone 3 tool dimostrativi (M0).

Pattern per ogni tool:
1. Decoratore @mcp.tool() con descrizione che il modello LLM consuma
2. Argomenti tipizzati con Pydantic / annotazioni Python
3. Body: chiamata al backend CARA via CaraClient
4. Ritorno: dict serializzabile in JSON

Tool M1 follow-up (cfr README): add_shopping, list_reminders,
add_reminder, search_memory.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from cara_mcp.client import CaraClient


log = logging.getLogger("cara-mcp")
mcp = FastMCP("cara")

_client: CaraClient | None = None


def _get_client() -> CaraClient:
    global _client
    if _client is None:
        _client = CaraClient()
    return _client


# ─── Tool: list_tasks ────────────────────────────────────────────────


@mcp.tool()
async def list_tasks(done: bool = False) -> dict[str, Any]:
    """Lista le task dell'utente CARA.

    Args:
        done: se True ritorna solo le task completate, se False solo le
              pending. Default False.

    Returns:
        Dict con `tasks` (list of {id, title, done, due_date, …}) e
        `count`.
    """
    client = _get_client()
    tasks = await client.get("/tasks")
    filtered = [t for t in tasks if bool(t.get("done")) == done]
    return {"tasks": filtered, "count": len(filtered)}


# ─── Tool: add_task ──────────────────────────────────────────────────


@mcp.tool()
async def add_task(
    title: str, due_date_iso: str | None = None
) -> dict[str, Any]:
    """Crea una nuova task in CARA.

    Args:
        title: titolo della task (obbligatorio, max 280 char).
        due_date_iso: scadenza in formato ISO 8601 UTC (es.
                      "2026-05-25T18:00:00Z"). Opzionale.

    Returns:
        Task creata con id, title, due_date, done=false.
    """
    body: dict[str, Any] = {"title": title}
    if due_date_iso:
        body["due_date"] = due_date_iso
    created = await _get_client().post("/tasks", body)
    return {"task": created, "ok": True}


# ─── Tool: list_shopping ─────────────────────────────────────────────


@mcp.tool()
async def list_shopping(only_to_buy: bool = True) -> dict[str, Any]:
    """Lista gli item nella lista della spesa di famiglia.

    Args:
        only_to_buy: se True (default) ritorna solo gli item non
                     ancora comprati. Se False include anche i bought.

    Returns:
        Dict con `items` e `count`.
    """
    items = await _get_client().get("/shopping")
    if only_to_buy:
        items = [it for it in items if not it.get("bought")]
    return {"items": items, "count": len(items)}


# ─── Bootstrap ───────────────────────────────────────────────────────


def run(transport: str = "stdio", port: int = 8500) -> int:
    """Avvia il server MCP."""
    logging.basicConfig(level=logging.INFO)
    log.info("Starting cara-mcp via %s", transport)
    try:
        if transport == "stdio":
            mcp.run()  # FastMCP default = stdio
        elif transport == "http":
            asyncio.run(mcp.run_sse_async(host="0.0.0.0", port=port))
        else:
            log.error("Unknown transport: %s", transport)
            return 1
    except KeyboardInterrupt:
        log.info("Interrupted")
    finally:
        if _client is not None:
            asyncio.run(_client.close())
    return 0
