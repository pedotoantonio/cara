"""add skills table

Revision ID: 6061bac37e44
Revises: a3f1c0e2b417
Create Date: 2026-05-04

First slice of the Skill Factory (v0.7). Only the `skills` table here.
Embeddings (`skill_intent_embeddings`) and run telemetry (`skill_runs`) come
in a later migration when those features land.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '6061bac37e44'
down_revision: str | None = 'a3f1c0e2b417'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'skills',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('intent_examples', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default='[]'),
        sa.Column('slot_extraction', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default='{}'),
        sa.Column('plan', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('response_template', sa.Text(), nullable=True),
        sa.Column('fallback_response', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False,
                  server_default='pending'),
        sa.Column('created_by_user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('approved_by_user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('auto_authored', sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index('skills_name_uniq', 'skills', ['name'], unique=True)
    op.create_index('skills_status_idx', 'skills', ['status'])


def downgrade() -> None:
    op.drop_index('skills_status_idx', table_name='skills')
    op.drop_index('skills_name_uniq', table_name='skills')
    op.drop_table('skills')
