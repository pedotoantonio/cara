"""Widget engine internals."""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

import structlog


log = structlog.get_logger(__name__)


class WidgetSize(str, Enum):
    """Card size on the dashboard. Widget itself decides what the user
    sees at each size — small ⇒ icon + 1 number, medium ⇒ +1 line of
    detail, large ⇒ full body."""
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


@dataclass
class WidgetContext:
    """Everything a widget might want to know about its caller.

    Designed wide so we don't have to bloat the constructor every time
    a new widget needs a piece of context. Widgets only read what they
    need; unused fields are just dead weight on the request-side stack.
    """

    user_id: int | None
    user_role: str = "guest"
    surface_class: str = "mobile"        # "wall" | "mobile" | "desktop" | "watch" | "tv"
    locale: str = "it-IT"
    timezone: str = "Europe/Rome"
    config: dict[str, Any] = field(default_factory=dict)  # per-widget user config


@dataclass
class WidgetData:
    """The shape every widget returns. Frontend renders by `kind`."""

    widget_id: str
    title: str
    kind: str                             # "summary" | "list" | "metric" | "action_grid" | …
    body: dict[str, Any] = field(default_factory=dict)
    deep_link: str | None = None          # path like "/tasks", "/weather"
    last_updated_unix: float | None = None
    error: str | None = None              # if non-None, frontend shows a friendly fail state

    def to_dict(self) -> dict[str, Any]:
        return {
            "widget_id": self.widget_id,
            "title": self.title,
            "kind": self.kind,
            "body": self.body,
            "deep_link": self.deep_link,
            "last_updated_unix": self.last_updated_unix,
            "error": self.error,
        }


class WidgetError(Exception):
    """Recoverable widget-level failure — surfaced to the user as a
    friendly inline error rather than a 500."""


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Widget(Protocol):
    """Every concrete widget implements this shape."""

    id: str                                # stable slug, e.g. "today_summary"
    title_default: str                     # localisable later; for now Italian
    refresh_interval_s: int                # cache hint to the frontend / SW
    available_for_roles: tuple[str, ...] = ()   # () = everyone

    async def render(
        self, ctx: WidgetContext, *, size: WidgetSize = WidgetSize.MEDIUM
    ) -> WidgetData: ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class WidgetRegistry:
    """Process-wide registry. Order is preserved (registration order is the
    default render order in the dashboard)."""

    def __init__(self) -> None:
        self._widgets: list[Widget] = []
        self._lock = threading.Lock()

    def register(self, widget: Widget) -> None:
        with self._lock:
            self._widgets = [w for w in self._widgets if w.id != widget.id]
            self._widgets.append(widget)

    def unregister(self, widget_id: str) -> None:
        with self._lock:
            self._widgets = [w for w in self._widgets if w.id != widget_id]

    def get(self, widget_id: str) -> Widget | None:
        with self._lock:
            for w in self._widgets:
                if w.id == widget_id:
                    return w
        return None

    def list(self) -> list[Widget]:
        with self._lock:
            return list(self._widgets)

    def available_for(self, role: str) -> list[Widget]:
        """Subset visible to a user with `role`. Empty `available_for_roles`
        means visible to everyone."""
        with self._lock:
            return [
                w for w in self._widgets
                if not getattr(w, "available_for_roles", ()) or role in w.available_for_roles
            ]

    async def render_many(
        self,
        widget_ids: Iterable[str],
        ctx: WidgetContext,
        *,
        size: WidgetSize = WidgetSize.MEDIUM,
    ) -> list[WidgetData]:
        """Render the requested widgets in order, swallowing per-widget
        errors as inline error payloads.

        A buggy widget MUST NEVER take down the whole dashboard. Any
        exception becomes a `WidgetData(error=...)` that the frontend
        can render as a small "couldn't load" card.
        """
        out: list[WidgetData] = []
        for wid in widget_ids:
            w = self.get(wid)
            if w is None:
                out.append(WidgetData(
                    widget_id=wid, title=wid, kind="error",
                    error="widget non trovato",
                ))
                continue
            try:
                payload = await w.render(ctx, size=size)
            except WidgetError as exc:
                payload = WidgetData(
                    widget_id=w.id, title=w.title_default, kind="error",
                    error=str(exc),
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("widget.render.exception", widget=w.id, error=str(exc))
                payload = WidgetData(
                    widget_id=w.id, title=w.title_default, kind="error",
                    error="errore interno",
                )
            out.append(payload)
        return out


_global_registry: WidgetRegistry | None = None
_global_lock = threading.Lock()


def get_default_registry() -> WidgetRegistry:
    """Lazy process-wide singleton."""
    global _global_registry
    with _global_lock:
        if _global_registry is None:
            _global_registry = WidgetRegistry()
        return _global_registry


def reset_default_registry_for_test() -> None:
    global _global_registry
    with _global_lock:
        _global_registry = None
