"""Health checks for the admin diagnostics page.

Each `check_*` coroutine returns a dict
    {"name": str, "status": "ok"|"warn"|"error", "latency_ms": int|None,
     "detail": str}

All checks have a hard 5 s timeout so the diagnostics page never blocks
on a stuck dependency.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from cara.config import settings

log = structlog.get_logger(__name__)


_TIMEOUT_S = 5.0


def _ok(name: str, *, ms: int | None, detail: str) -> dict[str, Any]:
    return {"name": name, "status": "ok", "latency_ms": ms, "detail": detail}


def _warn(name: str, *, detail: str, ms: int | None = None) -> dict[str, Any]:
    return {"name": name, "status": "warn", "latency_ms": ms, "detail": detail}


def _err(name: str, *, detail: str) -> dict[str, Any]:
    return {"name": name, "status": "error", "latency_ms": None, "detail": detail}


async def _with_timeout(coro: Any, name: str) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(coro, timeout=_TIMEOUT_S)
    except asyncio.TimeoutError:
        return _err(name, detail=f"timeout after {_TIMEOUT_S}s")
    except Exception as exc:  # noqa: BLE001
        return _err(name, detail=f"{exc.__class__.__name__}: {exc}")


# ---------- individual checks ----------------------------------------


async def check_db() -> dict[str, Any]:
    from sqlalchemy import text

    from cara.store.db import _sessionmaker

    if _sessionmaker is None:
        return _err("db", detail="engine not initialised")
    t0 = time.perf_counter()
    async with _sessionmaker() as s:
        await s.execute(text("SELECT 1"))
    return _ok("db", ms=int((time.perf_counter() - t0) * 1000), detail="postgres responsive")


async def check_redis() -> dict[str, Any]:
    import redis.asyncio as aioredis

    t0 = time.perf_counter()
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.ping()
    finally:
        await client.aclose()
    return _ok("redis", ms=int((time.perf_counter() - t0) * 1000), detail="reachable")


async def check_llm() -> dict[str, Any]:
    try:
        from cara.ai.llm import get_llm_service

        svc = get_llm_service()
        modes = getattr(svc, "available_modes", ["unknown"])
        active = getattr(svc, "mode", "unknown")
        return _ok("llm", ms=None, detail=f"mode={active}, available={modes}")
    except Exception as exc:  # noqa: BLE001
        return _err("llm", detail=f"not available: {exc}")


async def check_piper() -> dict[str, Any]:
    try:
        from cara.ai.tts import get_tts_service

        svc = get_tts_service()
        voices = svc.list_voices()
        loaded = [v for v in voices if (v.get("engine") or "") == "piper"]
        return _ok(
            "piper_tts",
            ms=None,
            detail=f"{len(loaded)} voci nel catalogo, default={settings.tts_default_voice}",
        )
    except Exception as exc:  # noqa: BLE001
        return _err("piper_tts", detail=f"{exc}")


async def check_whisper() -> dict[str, Any]:
    if not settings.whisper_enabled:
        return _warn("whisper_asr", detail="disabilitato in config")
    try:
        # Lazy: just check the cache dir exists; real model load happens
        # on first request to avoid blocking diagnostics.
        from pathlib import Path

        cache_dir = Path(settings.whisper_cache_dir)
        if cache_dir.exists() and any(cache_dir.iterdir()):
            return _ok("whisper_asr", ms=None, detail=f"cache pronta: {cache_dir}")
        return _warn("whisper_asr", detail="cache vuota — modello scaricato al primo uso")
    except Exception as exc:  # noqa: BLE001
        return _err("whisper_asr", detail=f"{exc}")


async def check_cda_search() -> dict[str, Any]:
    """Quick liveness probe of the search chain (no real query, just URL ping)."""
    import httpx

    if settings.cda_searxng_url:
        url = settings.cda_searxng_url.rstrip("/") + "/healthz"
        try:
            t0 = time.perf_counter()
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(url)
                ok = r.status_code < 500
            ms = int((time.perf_counter() - t0) * 1000)
            if ok:
                return _ok("cda_search", ms=ms, detail=f"SearXNG {url} ok")
            return _warn("cda_search", ms=ms, detail=f"SearXNG returned {r.status_code}")
        except Exception:  # noqa: BLE001
            pass
    # Fallback: just make sure DDG HTML host is reachable.
    try:
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.head("https://html.duckduckgo.com/")
        ms = int((time.perf_counter() - t0) * 1000)
        if r.status_code < 500:
            return _ok("cda_search", ms=ms, detail="DDG HTML reachable")
        return _warn("cda_search", ms=ms, detail=f"DDG returned {r.status_code}")
    except Exception as exc:  # noqa: BLE001
        return _err("cda_search", detail=f"{exc}")


async def check_intent_router() -> dict[str, Any]:
    try:
        from cara.services.event_log import stats
        from cara.services import intent_router  # noqa: F401

        s = stats()
        matches = s.get("intent_router.match", 0)
        return _ok(
            "intent_router",
            ms=None,
            detail=f"{matches} match nei recenti {sum(s.values())} eventi",
        )
    except Exception as exc:  # noqa: BLE001
        return _err("intent_router", detail=f"{exc}")


async def check_tts_piper_synth() -> dict[str, Any]:
    """Real round-trip: synthesize 1 short word, measure latency."""
    try:
        from cara.ai.tts import get_tts_service

        svc = get_tts_service()
        t0 = time.perf_counter()
        wav, _sr = await svc.synthesize_wav(text="ok", speed=1.0)
        ms = int((time.perf_counter() - t0) * 1000)
        if not wav:
            return _err("tts_synth", detail="empty WAV")
        return _ok("tts_synth", ms=ms, detail=f"{len(wav)} bytes WAV")
    except Exception as exc:  # noqa: BLE001
        return _err("tts_synth", detail=f"{exc}")


# ---------- runner ----------------------------------------------------


async def run_all() -> list[dict[str, Any]]:
    """Run every check concurrently with per-check 5 s timeout."""
    coros = [
        ("db", check_db()),
        ("redis", check_redis()),
        ("llm", check_llm()),
        ("piper_tts", check_piper()),
        ("whisper_asr", check_whisper()),
        ("cda_search", check_cda_search()),
        ("intent_router", check_intent_router()),
        ("tts_synth", check_tts_piper_synth()),
    ]
    results = await asyncio.gather(
        *[_with_timeout(c, name) for name, c in coros],
        return_exceptions=False,
    )
    return list(results)
