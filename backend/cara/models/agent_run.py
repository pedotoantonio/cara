"""AgentRun — observability row for each Celery task execution.

Every `@cara_task` decorated function writes one row here on completion
(success OR failure) so `/admin/agents` and `/admin/diagnostics` can
surface the agent's recent activity, error rates, and idempotency
state without having to query Celery's volatile result backend.

Idempotency: the `idempotency_key` UNIQUE constraint guards against
double-processing. A re-run with the same key just updates the
existing row's `started_at` / `finished_at` / `status` instead of
inserting a duplicate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cara.store.db import Base


# Status values used by the @cara_task decorator and the /admin/agents
# UI — kept as plain string constants (no Enum) so JSON serialisation
# stays simple and migrations don't need ENUM types.
AGENT_STATUS_RUNNING = "running"
AGENT_STATUS_OK = "ok"
AGENT_STATUS_FAILED = "failed"
AGENT_STATUS_SKIPPED = "skipped"   # idempotency_key already done
AGENT_STATUS_PARTIAL = "partial"   # finished within deadline but `incomplete=True`


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint(
            "agent_name", "task_name", "idempotency_key",
            name="uq_agent_runs_idempotency",
        ),
        Index("ix_agent_runs_agent_started", "agent_name", "started_at"),
        Index("ix_agent_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_name: Mapped[str] = mapped_column(String(40), nullable=False)
    task_name: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AGENT_STATUS_RUNNING,
        server_default=AGENT_STATUS_RUNNING,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_class: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
