"""Six extra widgets layered on top of the Step-7.2 starter catalog.

  - `budget_month`         current-month spending vs target per category
  - `kids_homework`         scuola/compiti task list filtered for kids
  - `routine_next`          next abitudine accettata da rilevare oggi
  - `cara_quote`            frase del giorno (deterministic by date)
  - `news_brief`            top 3 titoli da feed RSS
  - `radio_now_playing`     stazione radio attualmente attiva

Every widget conforms to the `Widget` Protocol (id, title_default,
refresh_interval_s, available_for_roles, async render). Adapter
callables get injected at construction time so unit tests use
fakes — production wiring lives in `api/v1/widgets.py`.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from cara.widgets.base import (
    WidgetContext,
    WidgetData,
    WidgetSize,
)


# ---------------------------------------------------------------------------
# Adapter signatures — production wiring lives in api/v1/widgets.py
# ---------------------------------------------------------------------------


# (year, month) → MonthRollup-like dict from cara.services.budgets
BudgetRollupFn = Callable[[int, int], Awaitable[dict[str, Any]]]

# (user_id) → list of {id, title, due_unix?, done} for school tasks
KidsHomeworkFn = Callable[[int], Awaitable[list[dict[str, Any]]]]

# (user_id) → list of {kind, weekday, hour_bucket, pattern, last_seen}
# accepted habits, sorted nearest-first
HabitNextFn = Callable[[int], Awaitable[list[dict[str, Any]]]]

# (category, limit) → list of {title, summary?, source, link, published?}
NewsBriefFn = Callable[[str, int], Awaitable[list[dict[str, Any]]]]

# () → {title, source, started_unix?} | None — currently-playing station
NowPlayingFn = Callable[[], Awaitable[dict[str, Any] | None]]

# (user_id) → professional diet report dict (energy + adherence + macros)
DietSummaryFn = Callable[[int], Awaitable[dict[str, Any] | None]]


@dataclass
class _ExtraFetchers:
    """Container for the optional fetchers each widget needs."""

    budget_rollup: BudgetRollupFn | None = None
    kids_homework: KidsHomeworkFn | None = None
    habit_next: HabitNextFn | None = None
    news_brief: NewsBriefFn | None = None
    now_playing: NowPlayingFn | None = None
    diet_summary: DietSummaryFn | None = None


# ---------------------------------------------------------------------------
# budget_month
# ---------------------------------------------------------------------------


class BudgetMonthWidget:
    id = "budget_month"
    title_default = "Budget del mese"
    refresh_interval_s = 300
    available_for_roles: tuple[str, ...] = ("parent",)

    def __init__(self, fetchers: _ExtraFetchers) -> None:
        self._f = fetchers

    async def render(
        self, ctx: WidgetContext, *, size: WidgetSize = WidgetSize.MEDIUM,
    ) -> WidgetData:
        body: dict[str, Any] = {"available": False}
        if self._f.budget_rollup is not None:
            from datetime import datetime
            try:
                from zoneinfo import ZoneInfo
                now = datetime.now(ZoneInfo(ctx.timezone or "Europe/Rome"))
            except Exception:
                now = datetime.now()
            try:
                rollup = await self._f.budget_rollup(now.year, now.month)
                body = {
                    "available": True,
                    "year": rollup.get("year"),
                    "month": rollup.get("month"),
                    "total_spent_cents": rollup.get("total_spent_cents", 0),
                    "total_target_cents": rollup.get("total_target_cents", 0),
                    "categories": rollup.get("categories", []),
                }
            except Exception:
                body = {"available": False, "error": "rollup_failed"}
        return WidgetData(
            widget_id=self.id, title=self.title_default, kind="budget",
            body=body, deep_link="/budgets",
            last_updated_unix=time.time(),
        )


# ---------------------------------------------------------------------------
# kids_homework
# ---------------------------------------------------------------------------


class KidsHomeworkWidget:
    id = "kids_homework"
    title_default = "Compiti"
    refresh_interval_s = 60
    available_for_roles: tuple[str, ...] = ("parent", "teen", "child")

    def __init__(self, fetchers: _ExtraFetchers) -> None:
        self._f = fetchers

    async def render(
        self, ctx: WidgetContext, *, size: WidgetSize = WidgetSize.MEDIUM,
    ) -> WidgetData:
        items: list[dict[str, Any]] = []
        if self._f.kids_homework is not None and ctx.user_id is not None:
            try:
                items = await self._f.kids_homework(ctx.user_id)
            except Exception:
                items = []
        # Cap by size.
        cap = {"small": 2, "medium": 4, "large": 8}.get(
            getattr(size, "value", str(size)), 4
        )
        return WidgetData(
            widget_id=self.id, title=self.title_default, kind="list",
            body={"items": items[:cap], "total": len(items)},
            deep_link="/tasks?category=homework",
            last_updated_unix=time.time(),
        )


# ---------------------------------------------------------------------------
# routine_next
# ---------------------------------------------------------------------------


_WEEKDAYS_IT = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
_HOUR_BUCKET_LABELS = (
    "00-03", "03-06", "06-09", "09-12",
    "12-15", "15-18", "18-21", "21-24",
)


class RoutineNextWidget:
    """Show the next-imminent accepted habit, with a friendly label."""

    id = "routine_next"
    title_default = "Prossima abitudine"
    refresh_interval_s = 300
    available_for_roles: tuple[str, ...] = ()

    def __init__(self, fetchers: _ExtraFetchers) -> None:
        self._f = fetchers

    async def render(
        self, ctx: WidgetContext, *, size: WidgetSize = WidgetSize.MEDIUM,
    ) -> WidgetData:
        body: dict[str, Any] = {"available": False}
        if self._f.habit_next is not None and ctx.user_id is not None:
            try:
                rows = await self._f.habit_next(ctx.user_id)
            except Exception:
                rows = []
            if rows:
                top = rows[0]
                wd = int(top.get("weekday", 0))
                hb = int(top.get("hour_bucket", 0))
                weekday_label = (
                    _WEEKDAYS_IT[wd] if 0 <= wd <= 6 else "?"
                )
                hour_label = (
                    _HOUR_BUCKET_LABELS[hb] if 0 <= hb < 8 else "?"
                )
                body = {
                    "available": True,
                    "kind": top.get("kind"),
                    "weekday": wd,
                    "weekday_label": weekday_label,
                    "hour_bucket": hb,
                    "hour_label": hour_label,
                    "pattern": top.get("pattern", {}),
                }
        return WidgetData(
            widget_id=self.id, title=self.title_default, kind="metric",
            body=body, deep_link="/admin/habits",
            last_updated_unix=time.time(),
        )


# ---------------------------------------------------------------------------
# cara_quote
# ---------------------------------------------------------------------------


# 30 brevi frasi italiane curate. La selezione è deterministica per
# data del calendario locale, così la frase non cambia ogni minuto.
_QUOTES: tuple[str, ...] = (
    "Una cosa per volta, fatta bene.",
    "Anche oggi va benissimo se ce l'hai messa tutta.",
    "I dettagli nascondono le cose importanti.",
    "Ascoltare è anche rispondere.",
    "Calma, dolcezza, lentezza — Hesse.",
    "Quando hai dubbi, scegli la cosa più gentile.",
    "Le piccole abitudini costruiscono i grandi anni.",
    "Il tempo che dedichi a chi ami non è mai sprecato.",
    "La memoria è un giardino: cosa stai annaffiando oggi?",
    "Un sorriso è una preghiera silenziosa.",
    "Chi insegna impara due volte — Seneca.",
    "Niente è da dare per scontato in casa.",
    "La pace non è il silenzio: è la risposta lenta.",
    "Il rispetto si allena come un muscolo.",
    "Ogni giorno è un piccolo capolavoro se lo guardi così.",
    "Le decisioni difficili invecchiano bene se prese con cura.",
    "C'è poesia anche nella lista della spesa.",
    "Una promessa mantenuta vale più di dieci dette bene.",
    "Le cose belle hanno bisogno di silenzio per crescere.",
    "Chi cucina per qualcuno gli dice: ti penso.",
    "La tecnologia è migliore quando serve, peggiore quando obbliga.",
    "Domandare è il primo gesto dell'amore.",
    "Le case migliori sono quelle dove si ride spesso.",
    "Risparmiare tempo è regalarlo a qualcuno.",
    "Ricominciare non è fallire: è imparare.",
    "Una telefonata fatta in tempo cambia un giorno.",
    "Le buone abitudini sono i nostri compagni più fedeli.",
    "La gentilezza è una valuta che non perde valore.",
    "Anche oggi siamo qui — e questo basta.",
    "Casa è dove la luce ti aspetta.",
)


class CaraQuoteWidget:
    """Frase del giorno — deterministic per data locale."""

    id = "cara_quote"
    title_default = "Pensiero del giorno"
    refresh_interval_s = 0           # static, no polling
    available_for_roles: tuple[str, ...] = ()

    async def render(
        self, ctx: WidgetContext, *, size: WidgetSize = WidgetSize.MEDIUM,
    ) -> WidgetData:
        from datetime import datetime
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo(ctx.timezone or "Europe/Rome"))
        except Exception:
            now = datetime.now()
        # day-of-year picks the same quote for everyone in the family
        # on the same day — light shared ritual.
        idx = now.timetuple().tm_yday % len(_QUOTES)
        return WidgetData(
            widget_id=self.id, title=self.title_default, kind="quote",
            body={"quote": _QUOTES[idx], "index": idx, "total": len(_QUOTES)},
            last_updated_unix=time.time(),
        )


# ---------------------------------------------------------------------------
# news_brief
# ---------------------------------------------------------------------------


class NewsBriefWidget:
    id = "news_brief"
    title_default = "Notizie in breve"
    refresh_interval_s = 600                      # 10 minuti
    available_for_roles: tuple[str, ...] = ()

    def __init__(
        self, fetchers: _ExtraFetchers, *, category: str = "all", limit: int = 3,
    ) -> None:
        self._f = fetchers
        self._category = category
        self._limit = max(1, min(limit, 10))

    async def render(
        self, ctx: WidgetContext, *, size: WidgetSize = WidgetSize.MEDIUM,
    ) -> WidgetData:
        # Allow per-user override via WidgetContext.config.
        cfg = ctx.config or {}
        category = cfg.get("category") or self._category
        limit = int(cfg.get("limit", self._limit))
        items: list[dict[str, Any]] = []
        if self._f.news_brief is not None:
            try:
                items = await self._f.news_brief(category, limit)
            except Exception:
                items = []
        return WidgetData(
            widget_id=self.id, title=self.title_default, kind="list",
            body={
                "category": category,
                "items": items[:limit],
            },
            deep_link="/news",
            last_updated_unix=time.time(),
        )


# ---------------------------------------------------------------------------
# radio_now_playing
# ---------------------------------------------------------------------------


class RadioNowPlayingWidget:
    id = "radio_now_playing"
    title_default = "In ascolto"
    refresh_interval_s = 60
    available_for_roles: tuple[str, ...] = ()

    def __init__(self, fetchers: _ExtraFetchers) -> None:
        self._f = fetchers

    async def render(
        self, ctx: WidgetContext, *, size: WidgetSize = WidgetSize.MEDIUM,
    ) -> WidgetData:
        body: dict[str, Any] = {"playing": False}
        if self._f.now_playing is not None:
            try:
                np = await self._f.now_playing()
            except Exception:
                np = None
            if np:
                body = {
                    "playing": True,
                    "title": np.get("title"),
                    "source": np.get("source"),
                    "started_unix": np.get("started_unix"),
                }
        return WidgetData(
            widget_id=self.id, title=self.title_default, kind="radio",
            body=body, deep_link="/radio",
            last_updated_unix=time.time(),
        )


# ---------------------------------------------------------------------------
# diet_summary — resoconto professionale della dieta
# ---------------------------------------------------------------------------


class DietSummaryWidget:
    """Resoconto nutrizionale professionale per il wallet.

    Aggrega in un colpo solo: bilancio energetico di oggi (introdotte /
    bruciate / fabbisogno / residuo, BMR+TDEE Mifflin-St Jeor),
    aderenza settimanale al piano per categoria proteica, media
    calorica e idratazione. È volutamente ricco — il wallet è il posto
    dove l'utente vuole il quadro completo a colpo d'occhio.

    Le calorie restano indicative (vedi modulo Nutrizione); il piano
    ragiona per frequenze settimanali.
    """

    id = "diet_summary"
    title_default = "Nutrizione"
    refresh_interval_s = 300
    available_for_roles: tuple[str, ...] = ()

    def __init__(self, fetchers: _ExtraFetchers) -> None:
        self._f = fetchers

    async def render(
        self, ctx: WidgetContext, *, size: WidgetSize = WidgetSize.MEDIUM,
    ) -> WidgetData:
        body: dict[str, Any] = {"available": False}
        if self._f.diet_summary is not None and ctx.user_id is not None:
            try:
                report = await self._f.diet_summary(ctx.user_id)
            except Exception:
                report = None
            if report:
                body = report
        return WidgetData(
            widget_id=self.id, title=self.title_default, kind="diet_summary",
            body=body, deep_link="/diet",
            last_updated_unix=time.time(),
        )


# ---------------------------------------------------------------------------
# Batch registration
# ---------------------------------------------------------------------------


def register_extras(
    fetchers: _ExtraFetchers,
    *,
    registry,
) -> None:
    """Register all extra widgets on `registry`."""
    registry.register(BudgetMonthWidget(fetchers))
    registry.register(KidsHomeworkWidget(fetchers))
    registry.register(RoutineNextWidget(fetchers))
    registry.register(CaraQuoteWidget())
    registry.register(NewsBriefWidget(fetchers))
    registry.register(RadioNowPlayingWidget(fetchers))
    registry.register(DietSummaryWidget(fetchers))
