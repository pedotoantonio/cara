"""HTTP client for the CARA backend.

cara-mcp non duplica logica del backend: traduce le tool call MCP in
chiamate REST. Questo file è il thin client che parla a CARA.

Auth: API token in env CARA_MCP_TOKEN passato come Bearer.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class CaraClient:
    """Thin async HTTP client per il backend CARA."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float = 30.0,
        verify_ssl: bool = False,  # cert self-signed locale
    ):
        self.base_url = (base_url or os.environ.get(
            "CARA_API_BASE",
            "https://192.168.1.23:8455/api/v1",
        )).rstrip("/")
        self.token = token or os.environ.get("CARA_MCP_TOKEN", "")
        if not self.token:
            raise RuntimeError(
                "CARA_MCP_TOKEN environment variable required"
            )
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            verify=verify_ssl,
            headers={"Authorization": f"Bearer {self.token}"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def get(self, path: str, **params: Any) -> Any:
        r = await self._client.get(path, params=params)
        r.raise_for_status()
        return r.json()

    async def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        r = await self._client.post(path, json=body or {})
        r.raise_for_status()
        if r.status_code == 204:
            return None
        return r.json()

    async def patch(self, path: str, body: dict[str, Any]) -> Any:
        r = await self._client.patch(path, json=body)
        r.raise_for_status()
        return r.json()

    async def delete(self, path: str) -> None:
        r = await self._client.delete(path)
        if r.status_code not in (200, 204):
            r.raise_for_status()
