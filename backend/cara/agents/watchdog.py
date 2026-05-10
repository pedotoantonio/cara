"""Watchdog agent — periodic health check + auto-recovery for the
catalogued CARA services. Beat schedule: every 30s on the `learn`
worker (which has the docker socket mounted).

Behaviour per service:

- color = green → reset bad-tick counter
- color = yellow / red / gray for ≥ `min_bad_ticks` consecutive ticks
  → log + Telegram alert + attempt `restart` (or `start` if exited)
- if recovery fails for ≥ `escalate_bad_ticks` ticks → louder alert
  (still keeps trying — easier to debug live)

Single-node note: real "cluster mode" requires a second physical node
to fail over to (or at least docker swarm w/ replicas across nodes).
On the NanoPC there is only one machine, so a hot-standby container
of the same service would just double RAM use without giving any HA.
What we *can* do is detect failure quickly and restart automatically;
that's what this watchdog implements.

Opt-in via admin setting `wall_watchdog_enabled` (default False) to
avoid surprising the user the first time we're enabled in production.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from cara.agents._base import _get_sessionmaker, cara_task


log = structlog.get_logger(__name__)


_REDIS_KEY_FMT = "watchdog:bad_ticks:{name}"
_REDIS_LAST_RECOVERY_FMT = "watchdog:last_recovery:{name}"
_REDIS_ALERT_KEY_FMT = "watchdog:last_alert:{name}"


@cara_task(agent="watchdog")
async def tick(idempotency_key: str | None = None) -> dict[str, Any]:
    """One pass over the catalogue. Cheap: 14 inspect calls + a couple
    of Redis reads, ~200 ms total in steady state."""
    from cara.api.v1.wall_services import CATALOG  # noqa: PLC0415
    from cara.config import settings  # noqa: PLC0415
    from cara.services import admin_settings as _admin  # noqa: PLC0415
    from cara.services import docker_client as dc  # noqa: PLC0415
    import redis.asyncio as redis_asyncio  # noqa: PLC0415

    sessionmaker = _get_sessionmaker()

    async with sessionmaker() as s:
        enabled = await _admin.get(s, "wall_watchdog_enabled")
        min_bad = int(await _admin.get(s, "wall_watchdog_min_bad_ticks") or 2)
        escalate_bad = int(
            await _admin.get(s, "wall_watchdog_escalate_bad_ticks") or 6
        )

    if enabled is not True:
        return {"skipped": "watchdog_disabled"}

    if not dc.is_socket_available():
        return {"skipped": "docker_socket_missing"}

    r = redis_asyncio.from_url(settings.redis_url)
    try:
        recovered: list[str] = []
        alerted: list[str] = []
        for entry in CATALOG:
            try:
                await _check_one(
                    r, entry, min_bad=min_bad, escalate_bad=escalate_bad,
                    recovered=recovered, alerted=alerted,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "watchdog.check_failed",
                    name=entry["name"], error=str(exc),
                )
        return {
            "checked": len(CATALOG),
            "recovered": recovered,
            "alerted": alerted,
        }
    finally:
        await r.aclose()


async def _check_one(
    r: Any,
    entry: dict[str, str],
    *,
    min_bad: int,
    escalate_bad: int,
    recovered: list[str],
    alerted: list[str],
) -> None:
    from cara.services import docker_client as dc  # noqa: PLC0415

    name = entry["name"]
    label = entry["label"]
    role = entry["role"]
    bad_key = _REDIS_KEY_FMT.format(name=name)

    insp = await dc.inspect_container(name)
    color = dc.state_color(insp)

    if color == "green":
        await r.delete(bad_key)
        return

    # Don't churn while a container is still inside its healthcheck
    # start-period (color=yellow but health=starting). Restarting it
    # only resets the clock and we end up in a restart loop. We also
    # reset bad_ticks so the previous "starting" period doesn't count
    # against us once the container actually goes healthy.
    if not dc.is_recovery_actionable(insp):
        await r.delete(bad_key)
        log.debug(
            "watchdog.benign_yellow",
            name=name, color=color, status=dc.short_status(insp),
        )
        return

    bad = int(await r.incr(bad_key))
    await r.expire(bad_key, 600)
    log.info(
        "watchdog.bad_tick",
        name=name, color=color, bad_ticks=bad,
        status=dc.short_status(insp),
    )

    if bad < min_bad:
        return

    # ── Decide an action ────────────────────────────────────────────
    state = (insp or {}).get("State", {}) or {}
    running = bool(state.get("Running"))
    action = "restart" if running else "start"

    # Stateful containers: still restart, but never replace. We'd never
    # try to recreate postgres on the fly — too risky.
    log.warning(
        "watchdog.recover",
        name=name, action=action, color=color, role=role,
        bad_ticks=bad,
    )
    try:
        await dc.container_action(name, action)
        recovered.append(f"{name}:{action}")
        await r.set(_REDIS_LAST_RECOVERY_FMT.format(name=name), str(bad), ex=3600)
    except Exception as exc:  # noqa: BLE001
        log.warning("watchdog.recover_failed", name=name, error=str(exc))

    # ── Telegram alert (rate-limited per service, 10 min) ───────────
    alert_key = _REDIS_ALERT_KEY_FMT.format(name=name)
    if await r.set(alert_key, "1", ex=600, nx=True):
        from cara.services.notify import (  # noqa: PLC0415
            Notification, enqueue_for_backend,
        )

        if bad >= escalate_bad:
            title = f"🚨 Servizio {label} non si recupera"
            body = (
                f"{name}: bad_ticks={bad}, ultimo stato {dc.short_status(insp)}. "
                f"Ho tentato {action} ma non è ancora green. Serve attenzione."
            )
            severity: str = "error"
        else:
            title = f"⚠️ Watchdog: {label}"
            body = (
                f"{name} → {dc.short_status(insp)}. Eseguo {action} automatico."
            )
            severity = "warn"

        notif = Notification(
            kind="watchdog.recover",
            title=title,
            body=body,
            tag=f"watchdog:{name}",
            speak_text=None,        # silent — we don't TTS infra alerts
            severity=severity,
            extra={"name": name, "action": action, "bad_ticks": bad},
        )
        try:
            await enqueue_for_backend(notif)
        except Exception as exc:  # noqa: BLE001
            log.warning("watchdog.notify_failed", name=name, error=str(exc))
        alerted.append(name)


async def _close_loop_safe(coro):
    """Helper to run a small async block without leaking warnings."""
    try:
        await coro
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        pass
