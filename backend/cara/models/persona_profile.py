"""PersonaProfile — per-user longitudinal profile, map-reduce-built by LLM.

Lumo-conversion Ondata β.

The profile is a Markdown document with fixed H3 sections:

  ## Identità
  ## Famiglia
  ## Lavoro
  ## Abitudini
  ## Gusti
  ## Salute
  ## Valori
  ## Stato emotivo
  ## Relazioni
  ## Contraddizioni    (only when there's something to record)
  ## Lacune            (only when there's something to record)

Within each section, claims are tagged either **STABILE** (durable
traits — allergies, profession, recurring hobbies) or **EPISODICO**
(time-bound — current mood, one-off events; ISO-dated, decay 30d).

The profile is injected into the chat system prompt every turn so the
1.5B model has longitudinal context it can't infer from its own
context window. Cap ~800 tokens (~3200 chars) by the chat layer; if
larger, the merge prompt is run a second time with a 'compress to N
tokens' hint.

Built nightly by `cara/learning/persona_profiler.py` via the
`persona_scheduler` lifespan tick in the backend. Eventually this will
move to a Celery 'learn' worker once cara-llm HTTP exists (ondata δ);
keeping it in-process for now because Celery workers can't talk to the
NPU.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cara.store.db import Base


class PersonaProfile(Base):
    """One row per user. Created lazily on first rebuild."""

    __tablename__ = "persona_profiles"

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # The profile itself, as one big Markdown blob. Cap is enforced
    # at write-time (~12k chars / ~3000 tokens of slack above the
    # injection cap), not at the DB level.
    markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Coarse confidence the profiler reports at end of EXTRACT/MERGE
    # ("Confidenza: X%"). 0..100. NULL = never built. Used to decide
    # whether to inject the profile into the chat prompt (below ~60
    # we'd rather skip than mislead).
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Watermark — last messages.id consumed by the most recent
    # incremental rebuild. NULL = full rebuild needed. The rebuild
    # job reads messages where id > this watermark, generates a
    # ProfileFragment, then MERGEs with `markdown`.
    last_message_id_consumed: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    # Optional structured view of the sections — convenient for the
    # admin UI to show one card per section without re-parsing the
    # markdown every render. Kept best-effort: source of truth is
    # `markdown`. Schema: {section_name: {"stable": [...], "episodic":
    # [{"text": "...", "date": "ISO"}]}}.
    sections: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )

    # Source / status hint. "ok" = last build succeeded. "low_confidence"
    # = built but below threshold (profile not injected into chat).
    # "failed" = last build raised. NULL = never built.
    last_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    last_built_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
