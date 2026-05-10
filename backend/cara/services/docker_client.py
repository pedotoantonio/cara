"""Thin async client for the local Docker daemon over its UNIX socket.

Used by `/api/v1/wall/services` and the watchdog beat task. Talks to
`/var/run/docker.sock` directly via `httpx` UDS transport — no extra
dependency. Only the handful of endpoints we need: list, inspect,
start, stop, restart.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

log = structlog.get_logger("cara.docker_client")

_SOCK_PATH = "/var/run/docker.sock"
_BASE_URL = "http://localhost"
_TIMEOUT = httpx.Timeout(10.0, connect=2.0)


def _client() -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(uds=_SOCK_PATH)
    return httpx.AsyncClient(base_url=_BASE_URL, transport=transport, timeout=_TIMEOUT)


def is_socket_available() -> bool:
    import os
    import stat

    try:
        st = os.stat(_SOCK_PATH)
        return stat.S_ISSOCK(st.st_mode)
    except OSError:
        return False


async def list_containers(*, all_: bool = True) -> list[dict[str, Any]]:
    async with _client() as c:
        r = await c.get("/containers/json", params={"all": "true" if all_ else "false"})
        r.raise_for_status()
        return r.json()


async def inspect_container(name_or_id: str) -> dict[str, Any] | None:
    async with _client() as c:
        r = await c.get(f"/containers/{name_or_id}/json")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


async def container_action(name_or_id: str, action: str, *, t_seconds: int = 10) -> None:
    """action ∈ {start, stop, restart, kill}. Raises on HTTP error."""
    if action not in {"start", "stop", "restart", "kill"}:
        raise ValueError(f"invalid action: {action}")
    params: dict[str, Any] = {}
    if action in ("stop", "restart"):
        params["t"] = str(t_seconds)
    async with _client() as c:
        r = await c.post(f"/containers/{name_or_id}/{action}", params=params)
        # 304 = already in target state. Treat as success.
        if r.status_code in (204, 304):
            return
        r.raise_for_status()


def state_color(inspect: dict[str, Any] | None) -> str:
    """green | yellow | red | gray for the UI pill."""
    if not inspect:
        return "gray"
    state = inspect.get("State", {}) or {}
    status = state.get("Status", "")
    health = (state.get("Health") or {}).get("Status")
    if status == "running":
        if health == "unhealthy":
            return "yellow"
        if health == "starting":
            return "yellow"
        return "green"
    if status in ("restarting", "created"):
        return "yellow"
    return "red"


def is_recovery_actionable(inspect: dict[str, Any] | None) -> bool:
    """Should the watchdog actually try to restart this container?

    False during the healthcheck *start period* (`health=starting`):
    a container that's still booting will look yellow but fixing it
    by `docker restart` only resets the clock — observed in practice
    on `cara-celery-beat`, whose 90 s start-period is longer than
    `min_bad_ticks * 30 s = 60 s`, so the watchdog was killing it
    every minute before it ever had a chance to flip to healthy.

    Genuine failure signals: status `exited`/`dead`/`removing`, or
    health `unhealthy` (the script ran and FAILED, not "didn't run
    yet"). `restarting` for too long also counts (we still increment
    `bad_ticks` and eventually escalate, but not on the very first
    tick — the bad_ticks gate at the call site handles that).
    """
    if not inspect:
        return False  # gone — not something restart can fix
    state = inspect.get("State", {}) or {}
    status = state.get("Status", "")
    health = (state.get("Health") or {}).get("Status")
    if status == "running":
        return health == "unhealthy"
    if status in ("exited", "dead"):
        return True
    if status == "restarting":
        return True  # stuck in restart loop — escalate
    return False


def short_status(inspect: dict[str, Any] | None) -> str:
    if not inspect:
        return "missing"
    state = inspect.get("State", {}) or {}
    status = state.get("Status", "unknown")
    health = (state.get("Health") or {}).get("Status")
    if health and status == "running":
        return f"{status}/{health}"
    return status


__all__ = [
    "is_socket_available",
    "list_containers",
    "inspect_container",
    "container_action",
    "state_color",
    "is_recovery_actionable",
    "short_status",
]
