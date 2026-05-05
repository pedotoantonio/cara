"""Tool-call telemetry endpoint — frontend reports parser/dispatch outcomes.

The 1.5B model emits tool calls in plain-text form
(`[TOOL: add_task(title="…")]`). The frontend parser at
`frontend/src/lib/tools.ts` is the canonical place where these get
turned into actual side-effects, and it's also the place where every
parsing/dispatch failure mode is observable. To populate the
`tool_call_metrics` table from there, the frontend POSTs every attempt
to this endpoint.

  POST /api/v1/tools/metric
       body = ToolMetricReport
       → 204 (recorded) or 422 (schema invalid)

  GET  /api/v1/tools/error-classes
       → list of canonical error_class slugs the frontend should pick from

The metric write is fire-and-forget on the server side: a failure to
persist must NEVER bubble back to the chat UI.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.learning import tool_metrics
from cara.learning.tool_metrics import (
    ERROR_EXEC_EXCEPTION,
    ERROR_MISSING_ARG,
    ERROR_PARSE_MALFORMED,
    ERROR_PARSE_TYPO_PREFIX,
    ERROR_PERMISSION_DENIED,
    ERROR_SCHEMA_INVALID,
    ERROR_UNKNOWN_TOOL,
)
from cara.models.user import User
from cara.store import get_session


router = APIRouter(prefix="/tools", tags=["tools"])


# Canonical slugs the frontend can use; exposed via GET /error-classes
# so the UI's dropdowns stay in sync without a separate constants file.
_ERROR_CLASSES = (
    ERROR_PARSE_TYPO_PREFIX,
    ERROR_PARSE_MALFORMED,
    ERROR_UNKNOWN_TOOL,
    ERROR_MISSING_ARG,
    ERROR_SCHEMA_INVALID,
    ERROR_PERMISSION_DENIED,
    ERROR_EXEC_EXCEPTION,
)


class ToolMetricReport(BaseModel):
    """One tool-call attempt as observed by the frontend dispatcher."""

    parse_ok: bool
    name_match: bool = False
    args_valid: bool = False
    executed: bool = False
    tool_name: str | None = Field(default=None, max_length=80)
    error_class: str | None = Field(default=None, max_length=40)
    raw_call: str | None = Field(default=None, max_length=2000)
    duration_ms: int | None = Field(default=None, ge=0, le=600_000)
    conversation_id: str | None = Field(default=None, max_length=120)


@router.post("/metric", status_code=status.HTTP_204_NO_CONTENT)
async def record_tool_metric(
    body: ToolMetricReport,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    """Persist one frontend-observed tool-call attempt."""
    await tool_metrics.record_attempt(
        session,
        parse_ok=body.parse_ok,
        name_match=body.name_match,
        args_valid=body.args_valid,
        executed=body.executed,
        tool_name=body.tool_name,
        error_class=body.error_class,
        raw_call=body.raw_call,
        user_id=user.id,
        conversation_id=body.conversation_id,
        duration_ms=body.duration_ms,
        commit=True,
    )


@router.get("/error-classes")
async def list_error_classes(
    _user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """Vocabulary of canonical error_class slugs.

    The frontend uses this to ensure it reports values the admin
    dashboards can group by. Adding a new slug requires bumping
    `cara.learning.tool_metrics` and re-deploying both ends.
    """
    return {"items": list(_ERROR_CLASSES)}
