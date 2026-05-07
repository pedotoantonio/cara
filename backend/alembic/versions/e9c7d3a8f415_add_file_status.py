"""add status + error_message to files

Revision ID: e9c7d3a8f415
Revises: d1a4b8c5e672
Create Date: 2026-05-07 00:00:00.000000

Phase 3: file ingestion moves from a synchronous POST to an async
Celery task. The API stores the blob immediately and returns 202;
the files-agent does the parsing in the background and flips status
to `ready` (or `failed`). Existing rows are pre-populated as `ready`
so the chat path that reads `text_content` keeps working unchanged.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "e9c7d3a8f415"
down_revision = "d1a4b8c5e672"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "files",
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="ready",
        ),
    )
    op.add_column(
        "files",
        sa.Column("error_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("files", "error_message")
    op.drop_column("files", "status")
