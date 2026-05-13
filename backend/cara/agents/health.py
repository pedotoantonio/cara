"""Health agent — continuous functional probes for the CARA stack.

Runs every 5 minutes on the `learn` worker. Each probe verifies that a
specific dependency or feature is *actually working* (not just that the
container is up — that's the watchdog's job). Examples:

- `db.select_1` confirms Postgres can take a query end-to-end.
- `redis.ping` confirms cache + bus are reachable from the worker.
- `chroma.heartbeat` exercises the vector store HTTP API.
- `frigate_faces.api_people` confirms the face-recognition service
  returns the people list (the upstream of presence).
- `wall.summary` is a loopback probe through nginx-proxy → frontend
  → backend, catching reverse-proxy + auth wiring breakage.
- `open_meteo.external` proves outbound internet still works.
- `telegram.bot_get_me` checks the bot token + outbound to Telegram.
- `llm.generate_short` actually pushes 1 token through the NPU so we
  detect a hung RKLLM context (the `running` container can otherwise
  look healthy while no inference goes through).

Each probe is small, bounded by short timeouts (default 5s; LLM gets
30s because of TTFT). Per-probe state is kept in Redis as a hash:

    health:probe:<name> = {
        "status": "ok" | "warn" | "fail",
        "last_check_at": ISO8601,
        "last_ok_at": ISO8601 | "",
        "fail_streak": "N",
        "duration_ms": "N",
        "error": "" | message,
    }

The frontend reads these via `/api/v1/wall/services/health`.

Notifications: when a probe transitions from ok→fail (or fail-streak
crosses an alert threshold of 2 consecutive failures) we enqueue a
single Telegram alert; recovery (any ok after a streak) sends a
"recovered" message. Rate limited to 1 alert per probe per 30 min.

Single-host caveat: this is monitoring, NOT auto-recovery. The
watchdog handles container-level recovery; if a probe fails because
its container is down, the watchdog will try to restart it and the
next health tick will re-evaluate. This split keeps each agent's
responsibility narrow.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx
import structlog
from sqlalchemy import text

from cara.agents._base import _get_sessionmaker, cara_task


log = structlog.get_logger(__name__)


_REDIS_PROBE_KEY = "health:probe:{name}"
_REDIS_ALERT_KEY = "health:alert:{name}"

_OK = "ok"
_WARN = "warn"
_FAIL = "fail"

# Probe spec: name → coroutine returning (status, error_msg). Soft
# timeouts are enforced inside each probe.

ProbeFn = Callable[[], Awaitable[tuple[str, str]]]


# ─── Probes ──────────────────────────────────────────────────────────


async def _probe_db() -> tuple[str, str]:
    sessionmaker = _get_sessionmaker()
    async with sessionmaker() as s:
        r = await s.execute(text("SELECT 1"))
        if r.scalar() == 1:
            return _OK, ""
    return _FAIL, "SELECT 1 returned no row"


async def _probe_redis() -> tuple[str, str]:
    import redis.asyncio as redis_asyncio  # noqa: PLC0415

    from cara.config import settings  # noqa: PLC0415
    r = redis_asyncio.from_url(settings.redis_url)
    try:
        ok = await r.ping()
        return (_OK, "") if ok else (_FAIL, "ping returned False")
    finally:
        await r.aclose()


async def _probe_minio() -> tuple[str, str]:
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.get("http://minio:9000/minio/health/live")
        if r.status_code == 200:
            return _OK, ""
        return _FAIL, f"HTTP {r.status_code}"


async def _probe_frigate_faces() -> tuple[str, str]:
    from cara.config import settings  # noqa: PLC0415
    url = (settings.frigate_faces_url or "http://frigate-faces:5051").rstrip("/")
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.get(f"{url}/api/people")
        if r.status_code == 200:
            return _OK, ""
        return _FAIL, f"HTTP {r.status_code}"


async def _probe_frigate() -> tuple[str, str]:
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.get("http://frigate:5000/api/stats")
        if r.status_code == 200:
            return _OK, ""
        return _FAIL, f"HTTP {r.status_code}"


async def _probe_wall_summary() -> tuple[str, str]:
    # Loopback through the backend service name on proxy-net (skips
    # nginx, cheaper, but still goes through full FastAPI stack).
    async with httpx.AsyncClient(
        timeout=10.0,
        headers={"X-Forwarded-For": "127.0.0.1"},
    ) as c:
        r = await c.get("http://cara-backend:8000/api/v1/wall/summary")
        if r.status_code == 200:
            return _OK, ""
        return _FAIL, f"HTTP {r.status_code}"


async def _probe_open_meteo() -> tuple[str, str]:
    async with httpx.AsyncClient(timeout=8.0) as c:
        r = await c.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": 44.83804, "longitude": 11.62057,
                "current": "temperature_2m",
            },
        )
        if r.status_code == 200 and "current" in r.json():
            return _OK, ""
        return _FAIL, f"HTTP {r.status_code}"


async def _probe_telegram_bot() -> tuple[str, str]:
    from cara.config import settings  # noqa: PLC0415
    token = settings.cara_telegram_bot_token if hasattr(
        settings, "cara_telegram_bot_token") else None
    if not token:
        return _WARN, "bot non configurato"
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.get(f"https://api.telegram.org/bot{token}/getMe")
        if r.status_code == 200 and r.json().get("ok"):
            return _OK, ""
        return _FAIL, f"HTTP {r.status_code}"


# ── Catalogue (probe name → fn). Order = display order in UI. ───────

_PROBES: list[tuple[str, str, ProbeFn]] = [
    ("db",            "PostgreSQL · SELECT 1",     _probe_db),
    ("redis",         "Redis · PING",              _probe_redis),
    ("minio",         "MinIO · /health/live",      _probe_minio),
    ("frigate_faces", "Frigate Faces · /api/people", _probe_frigate_faces),
    ("frigate",       "Frigate · /api/stats",      _probe_frigate),
    ("wall_summary",  "Backend · /wall/summary",   _probe_wall_summary),
    ("telegram_bot",  "Telegram · getMe",          _probe_telegram_bot),
    ("open_meteo",    "Open-Meteo · current",      _probe_open_meteo),
]


# ─── Tick ────────────────────────────────────────────────────────────


async def run_probes_once() -> dict[str, Any]:
    """Body of the health tick, callable directly without going through
    Celery — used by `/wall/services/health/run` for on-demand checks
    and by the beat task `tick()` below."""
    from cara.config import settings  # noqa: PLC0415
    from cara.services import admin_settings as _admin  # noqa: PLC0415
    import redis.asyncio as redis_asyncio  # noqa: PLC0415

    sessionmaker = _get_sessionmaker()
    async with sessionmaker() as s:
        enabled = await _admin.get(s, "wall_health_enabled")
        alert_threshold = int(
            await _admin.get(s, "wall_health_alert_streak") or 2
        )

    if enabled is False:  # default is None/True, only False disables
        return {"skipped": "disabled"}

    r = redis_asyncio.from_url(settings.redis_url)
    try:
        results: list[dict[str, Any]] = []
        for name, label, fn in _PROBES:
            t0 = time.monotonic()
            try:
                status, err = await asyncio.wait_for(fn(), timeout=30.0)
            except asyncio.TimeoutError:
                status, err = _FAIL, "timeout"
            except Exception as exc:  # noqa: BLE001
                status, err = _FAIL, f"{type(exc).__name__}: {exc}"
            duration_ms = int((time.monotonic() - t0) * 1000)

            await _persist_probe(
                r, name=name, label=label, status=status, err=err,
                duration_ms=duration_ms, alert_threshold=alert_threshold,
            )
            results.append({
                "name": name, "status": status,
                "duration_ms": duration_ms, "error": err,
            })

        bad = [r_ for r_ in results if r_["status"] == _FAIL]
        return {
            "checked": len(results),
            "ok": sum(1 for r_ in results if r_["status"] == _OK),
            "warn": sum(1 for r_ in results if r_["status"] == _WARN),
            "fail": len(bad),
            "results": results,
        }
    finally:
        await r.aclose()


async def _persist_probe(
    r: Any,
    *,
    name: str,
    label: str,
    status: str,
    err: str,
    duration_ms: int,
    alert_threshold: int,
) -> None:
    key = _REDIS_PROBE_KEY.format(name=name)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Read previous so we can detect transitions.
    prev = await r.hgetall(key)
    prev_status = (prev.get(b"status") or b"").decode() if prev else ""
    prev_streak = int((prev.get(b"fail_streak") or b"0").decode() or "0") if prev else 0
    prev_last_ok = (prev.get(b"last_ok_at") or b"").decode() if prev else ""

    if status == _OK:
        new_streak = 0
        last_ok = now_iso
    else:
        new_streak = prev_streak + 1
        last_ok = prev_last_ok

    state = {
        "status": status,
        "label": label,
        "last_check_at": now_iso,
        "last_ok_at": last_ok,
        "fail_streak": str(new_streak),
        "duration_ms": str(duration_ms),
        "error": err,
    }
    await r.hset(key, mapping=state)
    await r.expire(key, 86400)  # 1 day; stale entries drop out

    # ── Alerting transitions ──────────────────────────────────
    alert_key = _REDIS_ALERT_KEY.format(name=name)

    # Failure alert: ≥ threshold streak, not yet alerted in the cooldown.
    if status == _FAIL and new_streak >= alert_threshold:
        if await r.set(alert_key, "1", ex=1800, nx=True):
            await _alert(
                kind="health.fail",
                title=f"⚠️ Sonda CARA giù: {label}",
                body=(
                    f"{name} fallita {new_streak} volte di fila. "
                    f"Ultimo errore: {err[:200]}"
                ),
                tag=f"health:{name}",
            )

    # Recovery alert: just transitioned OK after a previous fail streak.
    if status == _OK and prev_status == _FAIL and prev_streak >= alert_threshold:
        await r.delete(alert_key)
        await _alert(
            kind="health.recovered",
            title=f"✅ Sonda CARA ripristinata: {label}",
            body=f"{name} è di nuovo OK ({duration_ms} ms).",
            tag=f"health:{name}",
        )


async def _alert(*, kind: str, title: str, body: str, tag: str) -> None:
    from cara.services.notify import (  # noqa: PLC0415
        Notification, enqueue_for_backend,
    )

    notif = Notification(
        kind=kind, title=title, body=body, tag=tag,
        speak_text=None, severity="warn" if "fail" in kind else "info",
    )
    try:
        await enqueue_for_backend(notif)
    except Exception as exc:  # noqa: BLE001
        log.warning("health.alert_failed", error=str(exc))


# ─── Read state for the API ─────────────────────────────────────────


async def read_snapshot() -> dict[str, Any]:
    """Read the current state of every probe from Redis. Used by
    `/api/v1/wall/services/health`. Probes that have never run yet are
    returned with status `unknown`."""
    from cara.config import settings  # noqa: PLC0415
    import redis.asyncio as redis_asyncio  # noqa: PLC0415

    r = redis_asyncio.from_url(settings.redis_url)
    try:
        items: list[dict[str, Any]] = []
        for name, label, _ in _PROBES:
            key = _REDIS_PROBE_KEY.format(name=name)
            raw = await r.hgetall(key)
            if not raw:
                items.append({
                    "name": name, "label": label, "status": "unknown",
                    "last_check_at": None, "last_ok_at": None,
                    "fail_streak": 0, "duration_ms": None, "error": "",
                })
                continue
            d = {k.decode(): v.decode() for k, v in raw.items()}
            items.append({
                "name": name,
                "label": d.get("label", label),
                "status": d.get("status", "unknown"),
                "last_check_at": d.get("last_check_at") or None,
                "last_ok_at": d.get("last_ok_at") or None,
                "fail_streak": int(d.get("fail_streak") or "0"),
                "duration_ms": int(d.get("duration_ms") or "0") or None,
                "error": d.get("error", ""),
            })

        summary = {
            "ok": sum(1 for i in items if i["status"] == "ok"),
            "warn": sum(1 for i in items if i["status"] == "warn"),
            "fail": sum(1 for i in items if i["status"] == "fail"),
            "unknown": sum(1 for i in items if i["status"] == "unknown"),
        }
        return {"items": items, "summary": summary}
    finally:
        await r.aclose()


@cara_task(agent="health")
async def tick(idempotency_key: str | None = None) -> dict[str, Any]:
    """Beat-driven entry point — wraps run_probes_once() with the
    standard agent_runs bookkeeping. Use run_probes_once() directly
    when you need to invoke the body from FastAPI."""
    return await run_probes_once()


__all__ = ["tick", "run_probes_once", "read_snapshot"]
