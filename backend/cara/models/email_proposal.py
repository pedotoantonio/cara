"""Pending proposals extracted from inbound email scans.

We never auto-create tasks from emails. Instead the scanner writes a
proposal row, the user sees it in `/me/proposte`, and accepts/rejects
explicitly. Idempotent on `message_id` so a re-scan doesn't duplicate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
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


class EmailProposal(Base):
    __tablename__ = "email_proposals"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "message_id",
            name="uq_email_proposal_user_msg",
        ),
        Index("ix_email_proposals_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    message_id: Mapped[str] = mapped_column(String(120), nullable=False)
    from_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposal_type: Mapped[str] = mapped_column(String(40), nullable=False)
    proposal_args: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source_layer: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_action: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )


class EmailLearningSignal(Base):
    """Aggregate signals from accept/reject. Used to auto-blacklist."""

    __tablename__ = "email_learning_signals"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "signal_type", "pattern",
            name="uq_email_learning_user_pattern",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    signal_type: Mapped[str] = mapped_column(String(40), nullable=False)
    pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    accepts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    rejects: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
