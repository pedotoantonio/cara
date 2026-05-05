"""Staged routing pipeline for CARA chat requests.

Conceptual flow:

    [user message + context] → Stage₁ → Hit?  → done
                                       → Miss → Stage₂ → Hit?  → done
                                                          → Miss → … → FallbackStage
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import structlog


log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Data carried through the pipeline
# ---------------------------------------------------------------------------


@dataclass
class RouteContext:
    """Everything a stage might need to decide whether to handle a request.

    Kept deliberately wide — adding a field is cheap, narrowing later is
    expensive. Stages that don't need a field just don't read it.
    """

    user_id: int | None
    message: str
    conversation_id: str | None = None
    history: list[dict[str, str]] = field(default_factory=list)
    files: list[str] = field(default_factory=list)  # FK ids, fully resolved later
    facts: list[str] = field(default_factory=list)  # top-k injected facts (Step 2.x)
    settings: dict[str, Any] = field(default_factory=dict)
    is_admin: bool = False
    role: str = "guest"
    # Free-form per-request scratchpad. Earlier stages can leave breadcrumbs
    # for later stages (e.g. NLU classifier output the LLM stage will use).
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class Hit:
    """A stage handled the request. Carries the response payload."""

    stage_name: str
    response: Any
    # Free-form metadata for telemetry (matched pattern, tool used, ...).
    meta: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0

    def is_hit(self) -> bool:
        return True


@dataclass
class Miss:
    """A stage declined the request. Reason is for telemetry only."""

    stage_name: str
    reason: str = "miss"
    duration_ms: int = 0

    def is_hit(self) -> bool:
        return False


StageResult = Hit | Miss


# ---------------------------------------------------------------------------
# Stage interface
# ---------------------------------------------------------------------------


@runtime_checkable
class Stage(Protocol):
    """A routing step. Implement `try_handle` and you're a stage."""

    name: str

    async def try_handle(self, ctx: RouteContext) -> StageResult: ...


# ---------------------------------------------------------------------------
# Trivial reference stages, useful for tests and as templates
# ---------------------------------------------------------------------------


class AlwaysMissStage:
    """Reference stage: always declines. Useful for testing pipeline flow."""

    name = "always_miss"

    def __init__(self, reason: str = "test_miss") -> None:
        self._reason = reason

    async def try_handle(self, ctx: RouteContext) -> StageResult:  # noqa: ARG002
        return Miss(stage_name=self.name, reason=self._reason)


class AlwaysHitStage:
    """Reference stage: always handles. Returns a fixed canned response."""

    name = "always_hit"

    def __init__(self, response: Any = "ok", stage_name: str = "always_hit") -> None:
        self._response = response
        self.name = stage_name

    async def try_handle(self, ctx: RouteContext) -> StageResult:  # noqa: ARG002
        return Hit(stage_name=self.name, response=self._response)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


# Optional callable a host may pass to record telemetry per stage. Kept as
# a parameter (not an import) so the pipeline package has zero coupling
# to `cara.learning.episodic`. Prevents an import cycle and lets tests
# inject a recording sink.
TelemetrySink = Callable[[str, str, str, int, RouteContext], Any]


class Pipeline:
    """Walks a list of stages until one returns a Hit.

    Properties worth knowing:

    - The dispatcher catches stage exceptions and converts them to a Miss
      with `reason="exception:<class>"`. One bad stage cannot brick the
      pipeline; the next stage gets a chance.
    - Empty pipeline returns a default Miss(stage_name="pipeline.empty"),
      which the caller is expected to handle as "fall through to LLM".
    - `telemetry_sink`, if provided, is called once per stage attempt.
    """

    def __init__(
        self,
        stages: Iterable[Stage] | None = None,
        *,
        telemetry_sink: TelemetrySink | None = None,
    ) -> None:
        self._stages: list[Stage] = list(stages or [])
        self._telemetry = telemetry_sink

    @property
    def stages(self) -> list[Stage]:
        return list(self._stages)

    def add(self, stage: Stage) -> Pipeline:
        """Append a stage. Returns self for chaining."""
        self._stages.append(stage)
        return self

    async def route(self, ctx: RouteContext) -> StageResult:
        if not self._stages:
            return Miss(stage_name="pipeline.empty", reason="no_stages")

        for stage in self._stages:
            t0 = time.perf_counter()
            try:
                result = await stage.try_handle(ctx)
            except Exception as exc:  # noqa: BLE001
                duration = int((time.perf_counter() - t0) * 1000)
                log.warning(
                    "router.stage.exception",
                    stage=stage.name,
                    error=str(exc),
                    error_class=type(exc).__name__,
                )
                result = Miss(
                    stage_name=stage.name,
                    reason=f"exception:{type(exc).__name__}",
                    duration_ms=duration,
                )
            else:
                result.duration_ms = int((time.perf_counter() - t0) * 1000)

            if self._telemetry is not None:
                try:
                    outcome = "hit" if result.is_hit() else "miss"
                    self._telemetry(
                        stage.name,
                        outcome,
                        getattr(result, "reason", "") if isinstance(result, Miss) else "",
                        result.duration_ms,
                        ctx,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("router.telemetry.failed", error=str(exc))

            if result.is_hit():
                return result

        # Every stage missed. Last-stage Miss is what we surface so the
        # caller knows where the chain bottomed out.
        return result  # noqa: F821 — set in the loop above
