"""Shopping list schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ShoppingItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    qty: str | None = None
    bought: bool
    created_at: datetime
    bought_at: datetime | None = None


class ShoppingItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    qty: str | None = Field(default=None, max_length=40)


class ShoppingItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    qty: str | None = Field(default=None, max_length=40)
    bought: bool | None = None
