"""Pydantic schemas for the /api/v1/memory/* endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FactOut(BaseModel):
    """One semantic-memory fact, as the user/admin sees it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    type: str
    text: str
    source: str
    confidence: float
    first_seen: datetime
    last_confirmed: datetime
    expiry: datetime | None = None
    active: bool


class FactCreate(BaseModel):
    """Manual creation by the user via the pin-message UI or /me/memory."""

    text: str = Field(min_length=2, max_length=500)
    type: str = Field(default="personal", max_length=32)
    confidence: float = Field(default=0.95, ge=0.0, le=1.0)


class FactPatch(BaseModel):
    """Update a fact's text/confidence or active flag."""

    text: str | None = Field(default=None, min_length=2, max_length=500)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    active: bool | None = None


class ExtractFactsRequest(BaseModel):
    """POST /memory/facts/extract — try to detect facts inside a message."""

    message: str = Field(min_length=1, max_length=2000)
    save: bool = Field(
        default=False,
        description="Persist any matched patterns immediately, with source='pattern'.",
    )
