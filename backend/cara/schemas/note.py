"""Note Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    body: str
    created_at: datetime
    updated_at: datetime


class NoteCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    body: str = Field(default="", max_length=20000)


class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=20000)
