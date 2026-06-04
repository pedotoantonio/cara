"""Add barcode + brand to food_items (Open Food Facts barcode scan).

Packaged products resolved by scanning their barcode (Open Food Facts)
are cached into the catalog so a re-scan is instant and works offline.

  * food_items.barcode — EAN/UPC, unique, indexed (lookup key on re-scan)
  * food_items.brand   — brand name from OFF (e.g. "Barilla")

Revision ID: c3f9a1e72b48
Revises: b2e8c4f1a937
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c3f9a1e72b48"
down_revision = "b2e8c4f1a937"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "food_items", sa.Column("barcode", sa.String(14), nullable=True)
    )
    op.add_column(
        "food_items", sa.Column("brand", sa.String(80), nullable=True)
    )
    op.create_index(
        "ix_food_items_barcode", "food_items", ["barcode"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_food_items_barcode", table_name="food_items")
    op.drop_column("food_items", "brand")
    op.drop_column("food_items", "barcode")
