"""Unit tests for `cara.ai.embeddings`. Mocks the heavy SentenceTransformer."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock

import pytest

from cara.ai.embeddings import (
    EmbeddingResult,
    EmbeddingService,
    cosine_similarity,
    top_k,
)


# --------------------------------------------------------------- cosine_similarity


def test_cosine_identical_vectors_score_one() -> None:
    v = [1.0 / math.sqrt(3), 1.0 / math.sqrt(3), 1.0 / math.sqrt(3)]
    assert abs(cosine_similarity(v, v) - 1.0) < 1e-6


def test_cosine_orthogonal_vectors_score_zero() -> None:
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    assert abs(cosine_similarity(a, b)) < 1e-6


def test_cosine_opposite_vectors_score_minus_one() -> None:
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert abs(cosine_similarity(a, b) - -1.0) < 1e-6


def test_cosine_handles_unnormalised_inputs() -> None:
    a = [3.0, 4.0]  # norm 5
    b = [3.0, 4.0]  # norm 5
    assert abs(cosine_similarity(a, b) - 1.0) < 1e-6


def test_cosine_zero_vector_returns_zero() -> None:
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_cosine_dim_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="dim mismatch"):
        cosine_similarity([1.0], [1.0, 2.0])


# --------------------------------------------------------------- top_k


def test_top_k_orders_by_similarity_desc() -> None:
    query = [1.0, 0.0]
    candidates = [
        ("low", [0.0, 1.0]),
        ("high", [1.0, 0.0]),
        ("mid", [0.7, 0.7]),
    ]
    out = top_k(query, candidates, k=3)
    payloads = [item for item, _ in out]
    assert payloads == ["high", "mid", "low"]


def test_top_k_respects_min_score() -> None:
    query = [1.0, 0.0]
    candidates = [
        ("close", [0.99, 0.14]),
        ("far", [0.0, 1.0]),
    ]
    out = top_k(query, candidates, k=5, min_score=0.5)
    payloads = [item for item, _ in out]
    assert payloads == ["close"]


def test_top_k_limits_results_to_k() -> None:
    query = [1.0, 0.0]
    candidates = [(f"c{i}", [1.0 - i * 0.001, 0.0]) for i in range(20)]
    out = top_k(query, candidates, k=3)
    assert len(out) == 3


# --------------------------------------------------------------- EmbeddingService


def _fake_model(vectors: list[list[float]]) -> MagicMock:
    """Build a stub model whose `encode` returns the given vectors."""
    m = MagicMock()
    # `encode` will be called with a list of texts; return as many vectors.
    m.encode = MagicMock(return_value=vectors)
    return m


@pytest.mark.asyncio
async def test_encode_single_returns_typed_result() -> None:
    model = _fake_model([[0.1, 0.2, 0.3]])
    svc = EmbeddingService(model=model)
    out = await svc.encode("ciao")
    assert isinstance(out, EmbeddingResult)
    assert out.text == "ciao"
    assert out.vector == [0.1, 0.2, 0.3]
    assert out.dim == 3


@pytest.mark.asyncio
async def test_encode_many_preserves_order() -> None:
    model = _fake_model([[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]])
    svc = EmbeddingService(model=model)
    out = await svc.encode_many(["a", "b", "c"])
    assert [r.text for r in out] == ["a", "b", "c"]
    assert out[0].vector == [1.0, 0.0]
    assert out[2].vector == [0.5, 0.5]


@pytest.mark.asyncio
async def test_encode_empty_list_returns_empty() -> None:
    model = _fake_model([])
    svc = EmbeddingService(model=model)
    out = await svc.encode_many([])
    assert out == []
    model.encode.assert_not_called()


# --------------------------------------------------------------- cache layer


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key):  # noqa: ANN001
        return self.store.get(key)

    async def set(self, key, value, *, ex=None):  # noqa: ANN001, ARG002
        self.store[key] = value if isinstance(value, str) else value.decode()
        return True


@pytest.mark.asyncio
async def test_encode_uses_cache_on_second_call() -> None:
    model = _fake_model([[0.1, 0.2, 0.3]])
    fake = FakeRedis()
    svc = EmbeddingService(model=model, redis_client=fake, dim=3)

    a = await svc.encode("ciao")
    b = await svc.encode("ciao")

    assert a.vector == b.vector
    # Model called once, second call served from cache.
    assert model.encode.call_count == 1


@pytest.mark.asyncio
async def test_encode_many_only_misses_hit_model() -> None:
    """If 2 of 3 texts are cached, only the 3rd is sent to the model."""
    model = MagicMock()
    fake = FakeRedis()
    svc = EmbeddingService(model=model, redis_client=fake, dim=3)

    # Pre-warm two cache entries.
    model.encode.return_value = [[0.1, 0.2, 0.3]]
    await svc.encode_many(["a"])
    model.encode.return_value = [[0.4, 0.5, 0.6]]
    await svc.encode_many(["b"])

    # Now mix: a (cached), b (cached), c (miss).
    model.encode.reset_mock()
    model.encode.return_value = [[0.7, 0.8, 0.9]]
    out = await svc.encode_many(["a", "b", "c"])

    assert out[0].vector == [0.1, 0.2, 0.3]
    assert out[1].vector == [0.4, 0.5, 0.6]
    assert out[2].vector == [0.7, 0.8, 0.9]
    # Only one call, with the single missed text.
    assert model.encode.call_count == 1
    args, _kwargs = model.encode.call_args
    assert args[0] == ["c"]


@pytest.mark.asyncio
async def test_cache_failure_falls_back_to_model() -> None:
    bad_redis = MagicMock()
    bad_redis.get = AsyncMock(side_effect=RuntimeError("redis dead"))
    bad_redis.set = AsyncMock(side_effect=RuntimeError("redis dead"))
    model = _fake_model([[0.1, 0.2, 0.3]])
    svc = EmbeddingService(model=model, redis_client=bad_redis)

    out = await svc.encode("ciao")  # must not raise
    assert out.vector == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_cache_rejects_corrupt_payload() -> None:
    fake = FakeRedis()
    model = _fake_model([[0.1, 0.2, 0.3]])
    svc = EmbeddingService(model=model, redis_client=fake, dim=3)

    # Plant a corrupt entry under the key the service would derive.
    key = svc._cache_key("ciao")
    fake.store[key] = "not-json"

    out = await svc.encode("ciao")
    assert out.vector == [0.1, 0.2, 0.3]
    assert model.encode.call_count == 1


def test_dim_property_advertises_384() -> None:
    """Production users should see the canonical model dim."""
    svc = EmbeddingService()
    assert svc.dim == 384
