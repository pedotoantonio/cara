"""Sentence embedding service for similarity search.

Used by:
- Semantic memory: top-k retrieval of facts relevant to the current query.
- Smart-home NLU: fuzzy-match a user utterance to the right device alias.
- Response cache (future): cluster near-duplicate queries to a shared key.
- Reflective batch: cluster router-misses by semantic similarity.

Model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- 384-dim output, 118 MB on disk, ~50 ms/sentence on the NanoPC CPU.
- Supports Italian *and* English in the same vector space — relevant
  because CARA conversations mix the two ("CARA, metti un meeting").

Design choices:

- **Lazy load**: the model is heavy (~150 MB resident) and slow to load
  (~3 s on first use). We import `sentence_transformers` and load the
  model inside the first `encode()` call, NOT at import time. Tests
  that mock the model never pay the cost.
- **Process singleton**: a single model instance per worker. No locking
  needed because PyTorch CPU inference is thread-safe; concurrent
  `encode()` calls share the GIL but produce correct results.
- **L2-normalised output**: `normalize_embeddings=True` so cosine
  similarity is just a dot product downstream (cheap pgvector ops).
- **Optional Redis cache**: short texts are repeatable ("ricordami le
  tasks"). Cache embeddings keyed by sha1(text) for 24 h. Disabled by
  default — pass a redis client to enable.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import structlog


log = structlog.get_logger(__name__)


_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_VECTOR_DIM = 384
_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 h

_model_lock = threading.Lock()
_model: Any | None = None  # SentenceTransformer instance, set on first use


def _load_model() -> Any:
    """Lazily import and load the sentence-transformers model.

    Kept out of module top-level so test runs that mock encoding don't
    pay the 3-second cold start.
    """
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        log.info("embeddings.loading", model=_MODEL_NAME)
        # Local import to keep startup snappy.
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(_MODEL_NAME)
        log.info("embeddings.loaded", model=_MODEL_NAME, dim=_VECTOR_DIM)
        return _model


def reset_model_for_test() -> None:
    """Test helper: drop the cached model so the next encode reloads."""
    global _model
    with _model_lock:
        _model = None


@dataclass
class EmbeddingResult:
    text: str
    vector: list[float]

    @property
    def dim(self) -> int:
        return len(self.vector)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Dot product of two L2-normalised vectors. -1.0..1.0.

    Falls back to a manual norm if vectors aren't normalised — cheap
    enough for ad-hoc lookups but the bulk path assumes pre-normalised.
    """
    if len(a) != len(b):
        raise ValueError(f"vector dim mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    # If both are already ~unit-length, dot is already cosine.
    if abs(norm_a - 1.0) < 1e-3 and abs(norm_b - 1.0) < 1e-3:
        return max(-1.0, min(1.0, dot))
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


def top_k(
    query: list[float],
    candidates: Iterable[tuple[Any, list[float]]],
    *,
    k: int = 5,
    min_score: float = 0.0,
) -> list[tuple[Any, float]]:
    """Return the top-`k` (item, similarity) pairs above `min_score`.

    `candidates` is an iterable of (opaque payload, vector). Sorted
    descending by similarity. Stable for ties (insertion order).
    """
    scored = []
    for payload, vec in candidates:
        score = cosine_similarity(query, vec)
        if score >= min_score:
            scored.append((payload, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:k]


class EmbeddingService:
    """Encode text → L2-normalised vectors, with optional Redis cache.

    `dim` defaults to 384 (the production model). Tests inject a fake
    encoder + the matching dim so cache validation accepts their vectors.
    Pass `model=` to inject a fake encoder; production leaves it None and
    the singleton lazy-loaded model is used.
    """

    def __init__(
        self,
        model: Any | None = None,
        redis_client: Any | None = None,
        dim: int = _VECTOR_DIM,
    ) -> None:
        self._model = model
        self._redis = redis_client
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    async def encode(self, text: str) -> EmbeddingResult:
        """Encode a single string."""
        results = await self.encode_many([text])
        return results[0]

    async def encode_many(self, texts: list[str]) -> list[EmbeddingResult]:
        """Encode a batch. Cache-aware: only uncached texts hit the model."""
        if not texts:
            return []

        cached: dict[int, list[float]] = {}
        miss_indices: list[int] = []
        miss_texts: list[str] = []

        # Cache lookup
        if self._redis is not None:
            for i, t in enumerate(texts):
                vec = await self._cache_get(t)
                if vec is not None:
                    cached[i] = vec
                else:
                    miss_indices.append(i)
                    miss_texts.append(t)
        else:
            miss_indices = list(range(len(texts)))
            miss_texts = list(texts)

        # Encode misses
        if miss_texts:
            model = self._model if self._model is not None else _load_model()
            # `encode` returns numpy array; wrap to list[list[float]].
            arr = model.encode(miss_texts, normalize_embeddings=True)
            # Be lenient about dtypes returned by mocks: list / list-of-lists / ndarray.
            try:
                miss_vectors = [list(map(float, v)) for v in arr]
            except TypeError:
                miss_vectors = [list(arr)] if isinstance(arr, list) else [arr.tolist()]
            for idx, vec in zip(miss_indices, miss_vectors, strict=True):
                cached[idx] = vec

            # Populate cache
            if self._redis is not None:
                for t, vec in zip(miss_texts, miss_vectors, strict=True):
                    await self._cache_set(t, vec)

        return [EmbeddingResult(text=texts[i], vector=cached[i]) for i in range(len(texts))]

    # ------------------------------------------------------------ cache impl

    def _cache_key(self, text: str) -> str:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
        return f"cara:emb:{self._dim}:{digest}"

    async def _cache_get(self, text: str) -> list[float] | None:
        try:
            raw = await self._redis.get(self._cache_key(text))
        except Exception as exc:  # noqa: BLE001
            log.warning("embeddings.cache.get_failed", error=str(exc))
            return None
        if raw is None:
            return None
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(data, list) or len(data) != self._dim:
            return None
        try:
            return [float(x) for x in data]
        except (TypeError, ValueError):
            return None

    async def _cache_set(self, text: str, vector: list[float]) -> None:
        try:
            await self._redis.set(
                self._cache_key(text),
                json.dumps(vector),
                ex=_CACHE_TTL_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("embeddings.cache.set_failed", error=str(exc))
