"""Workflow protocol + registry + shared dataclasses."""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import structlog


log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Inputs / Outputs
# ---------------------------------------------------------------------------


@dataclass
class WorkflowInput:
    """Whatever the user dropped into CARA: text, file id, or both.

    Workflows look at `kind` (the broad input class) and `payload`
    (typed bytes / decoded text / file id / metadata) to decide whether
    they want to engage.
    """

    kind: str                          # "image" | "pdf" | "text" | "audio" | "url"
    payload: dict[str, Any] = field(default_factory=dict)
    user_id: int | None = None
    conversation_id: str | None = None

    def get(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)


@dataclass
class ClassifyResult:
    """Did this workflow recognise the input?"""

    matches: bool
    confidence: float = 0.0            # 0.0..1.0
    reason: str = ""                    # human-readable, for telemetry
    hints: dict[str, Any] = field(default_factory=dict)  # passed to extract()


@dataclass
class StructuredData:
    """The output of `extract` — workflow-specific shape lives in `data`.

    `confidence` is the workflow's own assessment of how well it
    extracted the data; the UI uses it to decide whether to auto-confirm
    (high confidence) or always ask (low confidence).
    """

    kind: str                           # "receipt" | "bill" | "recipe" | ...
    data: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    raw_text: str = ""                  # source text/OCR for audit


@dataclass
class ProposedAction:
    """A single side-effect the user is asked to confirm."""

    tool: str                           # which existing tool/skill this maps to
    args: dict[str, Any] = field(default_factory=dict)
    summary: str = ""                   # one-line preview shown in confirm UI
    reversible: bool = True             # destructive actions = False, double-confirm

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "args": self.args,
            "summary": self.summary,
            "reversible": self.reversible,
        }


@dataclass
class ExecutionResult:
    """Per-action outcome after execute() runs."""

    action: ProposedAction
    ok: bool
    error: str | None = None
    output: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0

    @classmethod
    def success(cls, action: ProposedAction, output: dict[str, Any] | None = None,
                duration_ms: int = 0) -> ExecutionResult:
        return cls(action=action, ok=True, output=output or {}, duration_ms=duration_ms)

    @classmethod
    def failure(cls, action: ProposedAction, error: str,
                duration_ms: int = 0) -> ExecutionResult:
        return cls(action=action, ok=False, error=error, duration_ms=duration_ms)


class WorkflowError(Exception):
    """Workflow stopped before producing a result. Caller should treat
    this as a non-match — it's safe to fall back to chat."""


# ---------------------------------------------------------------------------
# Workflow protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Workflow(Protocol):
    """The shape every concrete workflow implements.

    Designed so the four phases can be tested independently — a
    workflow is just four pure-ish functions plus a name.
    """

    name: str
    version: str

    async def classify(self, inp: WorkflowInput) -> ClassifyResult: ...
    async def extract(
        self, inp: WorkflowInput, hints: dict[str, Any]
    ) -> StructuredData: ...
    async def propose(self, data: StructuredData) -> list[ProposedAction]: ...
    async def execute(
        self, actions: Iterable[ProposedAction]
    ) -> list[ExecutionResult]: ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class WorkflowRegistry:
    """Process-wide list of registered workflows.

    Order matters: `classify_first_match` walks workflows in registration
    order and returns the first one that recognises the input. Register
    more specific workflows before generic catch-alls.
    """

    def __init__(self) -> None:
        self._workflows: list[Workflow] = []
        self._lock = threading.Lock()
        self._enabled: dict[str, bool] = {}

    def register(self, workflow: Workflow) -> None:
        with self._lock:
            # Replace any prior registration of the same name.
            self._workflows = [w for w in self._workflows if w.name != workflow.name]
            self._workflows.append(workflow)
            self._enabled.setdefault(workflow.name, True)

    def unregister(self, name: str) -> None:
        with self._lock:
            self._workflows = [w for w in self._workflows if w.name != name]
            self._enabled.pop(name, None)

    def list(self) -> list[Workflow]:
        """Snapshot of registered workflows."""
        with self._lock:
            return list(self._workflows)

    def is_enabled(self, name: str) -> bool:
        with self._lock:
            return self._enabled.get(name, True)

    def set_enabled(self, name: str, enabled: bool) -> None:
        with self._lock:
            self._enabled[name] = enabled

    async def classify_first_match(
        self, inp: WorkflowInput, *, min_confidence: float = 0.5
    ) -> tuple[Workflow, ClassifyResult] | None:
        """First (workflow, classify_result) above `min_confidence`.

        Walks registered workflows in order. Skips disabled ones. Returns
        None if none claims the input.
        """
        for w in self.list():
            if not self.is_enabled(w.name):
                continue
            try:
                result = await w.classify(inp)
            except Exception as exc:  # noqa: BLE001
                log.warning("workflow.classify.exception",
                            workflow=w.name, error=str(exc))
                continue
            if result.matches and result.confidence >= min_confidence:
                return w, result
        return None


_global_registry: WorkflowRegistry | None = None
_global_lock = threading.Lock()


def get_default_registry() -> WorkflowRegistry:
    """Return the process-wide default registry (lazy)."""
    global _global_registry
    with _global_lock:
        if _global_registry is None:
            _global_registry = WorkflowRegistry()
        return _global_registry


def reset_default_registry_for_test() -> None:
    """Drop the singleton so tests start with a clean slate."""
    global _global_registry
    with _global_lock:
        _global_registry = None
