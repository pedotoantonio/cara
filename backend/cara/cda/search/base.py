"""Abstract search provider."""

from __future__ import annotations

from abc import ABC, abstractmethod

from cara.cda.base import SearchHit


class SearchProviderError(Exception):
    """Raised when a search provider has an unrecoverable failure (rate limit,
    network down, etc.). The chain is allowed to try the next one."""


class SearchProvider(ABC):
    name: str

    @abstractmethod
    async def search(self, query: str, *, limit: int = 10) -> list[SearchHit]: ...
