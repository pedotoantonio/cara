"""seed skill ricetta_to_spesa

Revision ID: c8a7d94e1f02
Revises: 6061bac37e44
Create Date: 2026-05-04

Migrates the hand-coded `recipe_chain` (Step 65) into a JSON Skill row in the
new `skills` table (Step 66 — Skill Factory v0.7 first slice). Same intent
regex, same pipeline (discover → extract → bulk insert), but data-driven so
new skills can be added without rebuilding the backend.
"""
from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'c8a7d94e1f02'
down_revision: str | None = '6061bac37e44'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SKILL_NAME = 'ricetta_to_spesa'

INTENT_PATTERN = (
    r"\b(?:aggiun\w+|mett\w+|metti\w*|inserisc\w+)\b"
    r".{0,30}?\bingredient\w+\b"
    r".{0,15}?(?:per|della|delle|dello|degli|dell[ie]|dei|del|di|de|d['’])\s+"
    r"(?:la|il|lo|le|i|gli|l['’]|fare\s+(?:la|il|lo|le|i|gli|l['’])?)?\s*"
    r"([\w'’àèéìòù\s\-]{3,80}?)"
    r"(?:\s+(?:alla|nella|in|sulla|sul)\s+(?:lista\s+(?:della\s+)?)?spesa\b|$)"
)

INTENT_EXAMPLES = [
    "aggiungi gli ingredienti della torta margherita alla lista della spesa",
    "metti gli ingredienti per la torta margherita nella spesa",
    "aggiungi gli ingredienti del tiramisù alla spesa",
    "aggiungimi gli ingredienti per fare il pesto alla spesa",
    "metti gli ingredienti della pasta al forno alla spesa",
    "aggiungi alla spesa gli ingredienti della pizza",
]

SLOT_EXTRACTION = {
    "dish": {"method": "regex", "pattern": INTENT_PATTERN, "group": 1, "required": True}
}

PLAN = {
    "steps": [
        {
            "id": "search",
            "tool": "discover",
            "args": {"query": "ricetta {dish} ingredienti", "kind": "article"},
        },
        {
            "id": "extract",
            "tool": "extract_recipe_ingredients",
            "args": {"text": "{search.text}", "max_items": 30},
        },
        {
            "id": "add",
            "tool": "add_shopping_bulk",
            "args": {"titles": "{extract.items}"},
        },
    ]
}

RESPONSE_TEMPLATE = (
    "Ho cercato la ricetta di {dish} (fonte: {search.source_domain}) e ho "
    "aggiunto {add.count} ingredienti alla lista della spesa: {add.preview}."
)

FALLBACK_RESPONSE = (
    "Non sono riuscita a trovare/estrarre la ricetta di {dish}. Ti lascio il "
    "link da aprire manualmente: {search.url}"
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO skills (
                name, description, intent_examples, slot_extraction, plan,
                response_template, fallback_response, status, auto_authored, version
            )
            VALUES (
                :name, :description,
                CAST(:intent_examples AS jsonb),
                CAST(:slot_extraction AS jsonb),
                CAST(:plan AS jsonb),
                :response_template, :fallback_response,
                'active', false, 1
            )
            ON CONFLICT (name) DO NOTHING
            """
        ),
        {
            "name": SKILL_NAME,
            "description": (
                "Cerca una ricetta su internet, estrae gli ingredienti dalla "
                "pagina e li aggiunge tutti alla lista della spesa."
            ),
            "intent_examples": json.dumps(INTENT_EXAMPLES, ensure_ascii=False),
            "slot_extraction": json.dumps(SLOT_EXTRACTION),
            "plan": json.dumps(PLAN),
            "response_template": RESPONSE_TEMPLATE,
            "fallback_response": FALLBACK_RESPONSE,
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM skills WHERE name = :n"), {"n": SKILL_NAME}
    )
