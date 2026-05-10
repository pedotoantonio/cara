"""Chat-specific Pipeline wiring (Step 0.2 phase D).

Phase C extracted the three deterministic routing tiers into stand-alone
`try_*` async functions and ran them via a 9-line for-loop. This phase
swaps the loop for the generic `cara.router.Pipeline.route(ctx)` —
same input/output, but now with:

  * **Per-stage telemetry**: every Hit/Miss is reported through a sink
    that records a `router.stage` event in episodic memory. The
    diagnostics page can chart "% of requests that exit at each stage".
  * **Exception isolation**: a buggy stage produces a classified Miss
    with reason="exception:<class>", the next stage gets a chance.
  * **Composability**: adding a new tier = adding one Stage subclass +
    one entry in CHAT_PIPELINE. No surgery in `chat()`.

The trick is bridging from `cara.router.RouteContext` (a dataclass)
to the request-bound state the existing `try_*` handlers expect
(SQLAlchemy session, User row, conversation row, file list). We pass
those through `RouteContext.extras` — a free-form dict the pipeline
forwards untouched.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from cara.api.v1._chat_routing import (
    try_intent_router,
    try_quick_calc,
    try_recipe_chain,
    try_skill_dispatcher,
    try_smarthome,
)
from cara.learning import episodic
from cara.router import Hit, Miss, Pipeline, RouteContext, StageResult


log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Stage wrappers
# ---------------------------------------------------------------------------
#
# Each Stage subclass adapts the corresponding try_* handler to the
# Pipeline contract. The handler stays the canonical implementation; the
# Stage is a thin adapter so we don't duplicate logic.


class _RoutingStage:
    """Common wrapping logic for the three routing tiers.

    Subclasses set `name` and `_handler`; they share the
    extras-unpacking + Hit/Miss conversion code below.
    """

    name: str = "abstract"
    _handler = None  # type: ignore[assignment]

    async def try_handle(self, ctx: RouteContext) -> StageResult:
        # The handler signature is the canonical (session, user, last_user_q,
        # attached_files, convo). We pull all five out of ctx.extras —
        # chat() is responsible for stuffing them in.
        try:
            session = ctx.extras["session"]
            user = ctx.extras["user"]
            convo = ctx.extras["convo"]
            attached_files = ctx.extras.get("attached_files", [])
        except KeyError as exc:
            return Miss(
                stage_name=self.name,
                reason=f"missing_ctx:{exc.args[0]}",
            )

        # message: str (RouteContext field) is the user's last turn.
        # We treat empty / None as "no query" → instant miss.
        last_user_q = ctx.message or None
        resp = await type(self)._handler(  # noqa: SLF001 — calling unbound
            session=session,
            user=user,
            last_user_q=last_user_q,
            attached_files=attached_files,
            convo=convo,
        )
        if resp is None:
            return Miss(stage_name=self.name, reason="no_match")
        return Hit(stage_name=self.name, response=resp)


class QuickCalcStage(_RoutingStage):
    name = "quick_calc"
    _handler = staticmethod(try_quick_calc)


class SmartHomeStage(_RoutingStage):
    name = "smarthome"
    _handler = staticmethod(try_smarthome)


class SkillDispatcherStage(_RoutingStage):
    name = "skill_dispatcher"
    _handler = staticmethod(try_skill_dispatcher)


class RecipeChainStage(_RoutingStage):
    name = "recipe_chain"
    _handler = staticmethod(try_recipe_chain)


class IntentRouterStage(_RoutingStage):
    name = "intent_router"
    _handler = staticmethod(try_intent_router)


class WebSearchStage(_RoutingStage):
    """Last-chance stage before the plain LLM: if the query asks about
    something happening *now* (events, news, weather, prices, "oggi a
    Ferrara") we run a web search and stream a grounded answer. See
    `_chat_web_search.try_web_search` for the heuristics + provider
    chain used."""
    name = "web_search"

    @staticmethod
    async def _handler(*, session, user, last_user_q, attached_files, convo):  # type: ignore[override]
        from cara.api.v1._chat_web_search import try_web_search  # noqa: PLC0415
        return await try_web_search(
            session=session, user=user, last_user_q=last_user_q,
            attached_files=attached_files, convo=convo,
        )


# ---------------------------------------------------------------------------
# Telemetry sink
# ---------------------------------------------------------------------------


def _telemetry_sink(
    stage_name: str,
    outcome: str,           # "hit" | "miss"
    reason: str,
    duration_ms: int,
    ctx: RouteContext,
) -> None:
    """Pipeline.route calls this once per stage attempt.

    Fires episodic.record_async fire-and-forget. We deliberately
    schedule it as a background task rather than awaiting — the sink is
    sync (the Pipeline contract calls it synchronously), and the chat
    hot path can't afford to block on a DB write per stage.
    """
    import asyncio

    payload: dict[str, Any] = {
        "stage": stage_name,
        "outcome": outcome,
        "reason": reason or "",
    }
    if ctx.message:
        # First 80 chars only — the full message is logged once at the
        # router.miss event when no stage handles it. Per-stage logging
        # is for observability, not retention.
        payload["query_preview"] = ctx.message[:80]

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Called outside an event loop (shouldn't happen in production
        # but is defensive against test harnesses).
        return

    loop.create_task(
        episodic.record_async(
            kind="router.stage",
            user_id=ctx.user_id,
            ref_id=ctx.conversation_id,
            outcome=outcome,
            duration_ms=duration_ms,
            payload=payload,
        )
    )


# ---------------------------------------------------------------------------
# Pipeline factory + module-level singleton
# ---------------------------------------------------------------------------


def build_chat_pipeline() -> Pipeline:
    """Construct the chat routing pipeline. Cheap — the stage objects
    hold no state, they're pure adapters."""
    return Pipeline(
        stages=[
            QuickCalcStage(),
            SmartHomeStage(),
            SkillDispatcherStage(),
            RecipeChainStage(),
            IntentRouterStage(),
            # Web fallback is INTENTIONALLY last: every cheaper tier
            # gets first dibs (regex/skill/recipe match without a
            # network round-trip), and we only burn a SearXNG/DDG call
            # for queries the deterministic stages don't recognise.
            WebSearchStage(),
        ],
        telemetry_sink=_telemetry_sink,
    )


# One Pipeline per process. The Stage instances are stateless, so this
# is safe to share across requests.
CHAT_PIPELINE: Pipeline = build_chat_pipeline()


# ---------------------------------------------------------------------------
# High-level helper used by chat()
# ---------------------------------------------------------------------------


async def execute_pipeline_collect(
    *,
    session: Any,
    user: Any,
    text: str,
    convo: Any = None,
    conversation_id: str | None = None,
) -> str | None:
    """Run the chat Pipeline non-streaming and return the assembled
    text, or `None` when every stage missed.

    Used by surfaces that don't speak SSE (Telegram bot, scheduled
    proactivity rules, scripted automations). The deterministic stages
    (intent_router, skill_dispatcher, recipe_chain) all emit a single
    canned `token` frame followed by `done`, so a string concatenation
    over the parsed SSE body is enough — we don't need to handle
    multi-chunk LLM streaming here. A miss means the caller should
    fall through to its own LLM path (Telegram falls back to
    `_generate_reply`).
    """
    import json  # noqa: PLC0415

    resp = await route_chat_request(
        session=session,
        user=user,
        last_user_q=text,
        attached_files=[],
        convo=convo,
        conversation_id=conversation_id,
    )
    if resp is None:
        return None

    parts: list[str] = []
    body_iter = resp.body_iterator
    async for chunk in body_iter:
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8", errors="replace")
        for raw_line in chunk.splitlines():
            line = raw_line.strip()
            if not line.startswith("data:"):
                continue
            data_json = line[5:].strip()
            if not data_json:
                continue
            try:
                ev = json.loads(data_json)
            except json.JSONDecodeError:
                continue
            text_part = ev.get("text") if isinstance(ev, dict) else None
            if isinstance(text_part, str):
                parts.append(text_part)
    out = "".join(parts).strip()
    return out or None


async def route_chat_request(
    *,
    session: Any,
    user: Any,
    last_user_q: str | None,
    attached_files: list,
    convo: Any,
    conversation_id: str | None,
):
    """Build a RouteContext, walk the pipeline, return the Hit response or None.

    `chat()` calls this once before falling through to the LLM. Returns:
      - a `StreamingResponse` if any stage handled the request
      - `None` if every stage missed (caller should proceed to LLM)
    """
    ctx = RouteContext(
        user_id=user.id,
        message=last_user_q or "",
        conversation_id=conversation_id,
        files=[str(f.id) if hasattr(f, "id") else str(f) for f in attached_files],
        role=getattr(user, "role", "guest") or "guest",
        is_admin=bool(getattr(user, "is_admin", False)),
        extras={
            "session": session,
            "user": user,
            "convo": convo,
            "attached_files": attached_files,
        },
    )

    t_start = time.perf_counter()
    result = await CHAT_PIPELINE.route(ctx)
    elapsed = int((time.perf_counter() - t_start) * 1000)

    if result.is_hit():
        log.info(
            "chat.pipeline.hit",
            stage=result.stage_name,
            duration_ms=elapsed,
        )
        return result.response  # StreamingResponse from a try_* handler

    log.info(
        "chat.pipeline.miss",
        last_stage=result.stage_name,
        reason=getattr(result, "reason", ""),
        duration_ms=elapsed,
    )
    return None
