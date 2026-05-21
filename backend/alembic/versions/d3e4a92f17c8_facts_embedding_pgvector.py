"""facts.embedding → pgvector(384) + HNSW cosine index

Revision ID: d3e4a92f17c8
Revises: c4e1f8b3a972
Create Date: 2026-05-13 13:30:00.000000

Phase A of the RAG-on-pgvector rollout (item 1 of FOLLOWUP-2026-05-12.md).

`facts.embedding` was JSONB (a list[float] payload) and `top_k_for_query`
did Python-side cosine. With only a handful of facts that was fine, but
the moment we want to ingest notes + conversation summaries the Python
path crosses the line. pgvector + HNSW gives us SQL-side cosine in O(log n).

We drop the JSONB column rather than try to cast — the family fact table
is tiny (1-2 rows today) and the embedding model may have changed since
those rows were written; the indexer will repopulate from `text`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector


revision = "d3e4a92f17c8"
down_revision = "c4e1f8b3a972"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector extension was already created by the face migration; this is
    # idempotent and keeps the migration self-contained if facts ship first
    # on a fresh DB.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Drop + recreate. ALTER ... USING to convert JSONB→vector is awkward
    # (would need a CAST through text and a hand-rolled parser) and the
    # data is cheap to regenerate from `facts.text`.
    op.drop_column("facts", "embedding")
    op.add_column(
        "facts",
        sa.Column("embedding", Vector(384), nullable=True),
    )

    # HNSW cosine — same pattern as `face_descriptors`. The `<=>` operator
    # in cosine queries lands here; without the index the scanner would
    # fall back to sequential cosine.
    op.execute(
        "CREATE INDEX idx_facts_embedding_hnsw "
        "ON facts USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_facts_embedding_hnsw")
    op.drop_column("facts", "embedding")
    op.add_column(
        "facts",
        sa.Column("embedding", sa.dialects.postgresql.JSONB, nullable=True),
    )
