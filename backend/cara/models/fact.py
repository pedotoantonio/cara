"""Fact ORM model — semantic memory of stable facts about the family.

A fact is a sentence-level claim CARA has decided is worth remembering:

- "Antonio è allergico ai pomodori"
- "A Marco piacciono le serie sci-fi"
- "Casa Pedoto cena alle 20:00"
- "Sara torna da scuola intorno alle 16:30"

Facts power top-k retrieval into the chat system prompt: the highest-
scored facts for the current question are injected so CARA can answer
in context ("posso mangiare la pizza?" → fact about mozzarella allergy
→ careful answer).

Source provenance matters:

- `explicit`   user typed/said "ricorda che…" or pinned a message
- `pattern`    deterministic regex caught it ("sono allergic[oa] a X")
- `inferred`   future cloud-LLM extraction (Phase D, opt-in admin)

We store the embedding in a JSONB array of floats. **Why JSONB and not
pgvector?** pgvector adds a Postgres extension we'd otherwise have to
install at provisioning time. JSONB works on every Postgres without
extras, costs us native vector index ops (we do top-k in Python for
now), and lets us migrate to pgvector later by ALTERing the column type.
For a family-scale fact base (<10k rows), in-memory cosine top-k over
JSONB-stored vectors is plenty fast.

NOT yet imported in `cara/models/__init__.py` — same reason as Event /
ToolCallMetric / Device. Wire after Antonio's Step 66 commit.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cara.store.db import Base


# ----------------- Type slugs (kept here as constants so callers don't
#                   spell them by hand and SQL aggregations stay stable)

FACT_TYPE_PREFERENCE = "preference"
FACT_TYPE_ALLERGY = "allergy"
FACT_TYPE_HABIT = "habit"
FACT_TYPE_RELATION = "relation"
FACT_TYPE_SCHEDULE = "schedule"
FACT_TYPE_PERSONAL = "personal"
FACT_TYPE_MEDICAL = "medical"

FACT_SOURCE_EXPLICIT = "explicit"
FACT_SOURCE_PATTERN = "pattern"
FACT_SOURCE_INFERRED = "inferred"
FACT_SOURCE_PIN = "pin"


class Fact(Base):
    """One semantic-memory row about (or for) a user."""

    __tablename__ = "facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # NULL = family-wide ("a casa Pedoto si cena alle 20")
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )

    type: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    source: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0,
                                              server_default="1.0")

    # 384-d embedding stored as JSONB array. None until the embedding
    # service has run on this row (we index lazily in a background job).
    embedding: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)

    # Audit + lifecycle
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_confirmed: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expiry: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Optional pointer back to the conversation/event that produced this fact.
    source_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)

    __table_args__ = (
        Index("facts_user_active", "user_id", "active"),
        Index("facts_type", "type"),
        Index("facts_source", "source"),
    )
