"""Pydantic Intent classes for the LifeOps NLU router.

Discriminated union per la risposta del router. Ogni intent ha
`kind` come campo discriminator + tipi specifici per i campi.

M1 supporta solo 4 kind: reminder, list_add, list_query, list_done.
M2 estende a note_*, transaction_*, finance_query.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class ReminderIntent(BaseModel):
    kind: Literal["reminder"] = "reminder"
    title: str = Field(..., min_length=1, max_length=280)
    fires_at: datetime | None = None  # absolute UTC
    rrule: str | None = None
    urgent: bool = False
    delivery_hint: str | None = None  # "in cucina", "via push"


class ListAddIntent(BaseModel):
    kind: Literal["list_add"] = "list_add"
    list_slug: str
    item: str = Field(..., min_length=1, max_length=280)
    qty: float | None = None
    unit: str | None = None


class ListQueryIntent(BaseModel):
    kind: Literal["list_query"] = "list_query"
    list_slug: str | None = None


class ListDoneIntent(BaseModel):
    kind: Literal["list_done"] = "list_done"
    list_slug: str
    item_substring: str


class UnsureIntent(BaseModel):
    kind: Literal["unsure"] = "unsure"
    reason: str
    suggested_clarification: str | None = None


Intent = Annotated[
    Union[
        ReminderIntent,
        ListAddIntent,
        ListQueryIntent,
        ListDoneIntent,
        UnsureIntent,
    ],
    Field(discriminator="kind"),
]


__all__ = [
    "Intent",
    "ReminderIntent",
    "ListAddIntent",
    "ListQueryIntent",
    "ListDoneIntent",
    "UnsureIntent",
]
