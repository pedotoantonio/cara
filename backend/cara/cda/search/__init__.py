"""Search abstraction. Provider chain (SearXNG → DDG) selectable from admin."""

from cara.cda.search.base import SearchProvider, SearchProviderError
from cara.cda.search.chain import ProviderChain, build_default_chain
from cara.cda.search.ddg import DDGProvider
from cara.cda.search.searxng import SearXNGProvider

__all__ = [
    "DDGProvider",
    "ProviderChain",
    "SearchProvider",
    "SearchProviderError",
    "SearXNGProvider",
    "build_default_chain",
]
