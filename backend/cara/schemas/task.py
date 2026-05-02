"""Task (to-do) Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    done: bool
    created_at: datetime
    completed_at: datetime | None = None
    due_date: datetime | None = None


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    due_date: datetime | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    done: bool | None = None
    due_date: datetime | None = None
