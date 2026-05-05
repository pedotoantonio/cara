"""Tool-call telemetry — every attempt the LLM makes to invoke a tool.

CARA's 1.5B model has tool-calling reliability around 60-70% in production.
Without per-attempt telemetry, every workaround we add (tolerant parser,
grammar-constrained decoding, retry strategy) is a guess. This table is
the substrate for "what's actually breaking?"

Each attempt produces one row, regardless of outcome:

- `parse_ok=False` → the model output couldn't be parsed as a tool-call
  shape at all (typo prefix `TUTOOL`, malformed args, etc.)
- `parse_ok=True && name_match=False` → parsed, but the tool name doesn't
  exist in the registry (typo / hallucination)
- `parse_ok=True && name_match=True && args_valid=False` → tool exists but
  args don't match the schema (missing required, wrong type)
- everything True && executed=True → success path

`error_class` carries a short slug ("typo_prefix", "missing_arg",
"unknown_tool", "schema_invalid", "permission_denied", "exec_exception")
so SQL aggregations are cheap.

NOT yet imported in cara/models/__init__.py — wired after Step 66 merge.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from cara.store.db import Base


class ToolCallMetric(Base):
    """One attempted tool call, with the entire failure-mode breakdown."""

    __tablename__ = "tool_call_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Stage gates — each True only if the previous one was True too.
    parse_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    name_match: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    args_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    tool_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_class: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)

    # Capped raw text — never the full prompt, just the tool-call snippet
    # the model produced, so we can eyeball failure modes without bloating
    # the row.
    raw_call: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional duration of the underlying tool execution (NULL when the
    # attempt failed before that point).
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Conversation tie-in for "show me failed tool calls in this chat".
    conversation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    __table_args__ = (
        Index("tool_metrics_ts", "ts"),
        Index("tool_metrics_tool_ts", "tool_name", "ts"),
        Index("tool_metrics_user_ts", "user_id", "ts"),
    )
