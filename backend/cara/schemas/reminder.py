"""Pydantic schemas for the Reminders (Memorial) module."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ─── Templates ─────────────────────────────────────────────────────


class TemplateField(BaseModel):
    """One question rendered in the guided form."""
    key: str
    label: str
    # "text", "datetime", "date", "family_picker", "lead_time_picker", "select"
    type: str
    required: bool = False
    placeholder: str | None = None
    # Optional list of choices for "select" type.
    options: list[dict[str, str]] | None = None


class ReminderTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    category: str
    title_it: str
    icon: str
    fields: list[TemplateField]
    default_lead_times: list[int]
    default_recurrence: str | None = None
    order_in_category: int


# ─── Reminders ─────────────────────────────────────────────────────


class ReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: int
    family_id: int | None = None
    template_slug: str | None = None
    category: str
    title: str
    notes: str | None = None
    due_at: datetime
    recurrence: str | None = None
    recurrence_until: date | None = None
    lead_times: list[int]
    channels: dict[str, Any]
    status: str
    snooze_until: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ReminderCreate(BaseModel):
    """
    Two shapes accepted:

      A) Guided (preferred): `template_slug` + `due_at` + optional
         per-field overrides via `extras`. The service resolves the
         template, builds `title` from the template + extras, and
         copies `default_lead_times` / `default_recurrence`.

      B) Free-form: pass `title`, `category`, `due_at` directly.

    `family_id` is optional and points at a user row (the "subject"
    of the reminder, e.g. a child or a parent).
    """
    template_slug: str | None = None
    category: str | None = None
    title: str | None = Field(default=None, max_length=300)
    notes: str | None = None
    family_id: int | None = None
    due_at: datetime
    recurrence: str | None = None
    recurrence_until: date | None = None
    lead_times: list[int] | None = None
    channels: dict[str, Any] | None = None
    extras: dict[str, Any] | None = None  # per-field values from the form


class ReminderUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    notes: str | None = None
    due_at: datetime | None = None
    family_id: int | None = None
    recurrence: str | None = None
    recurrence_until: date | None = None
    lead_times: list[int] | None = None
    channels: dict[str, Any] | None = None
    status: str | None = None


class SnoozeIn(BaseModel):
    duration_minutes: int | None = Field(default=None, ge=5, le=60 * 24 * 30)
    until: datetime | None = None


# ─── Wall / widget payload ────────────────────────────────────────


class ReminderBrief(BaseModel):
    """Lightweight shape for widgets / Wall strip."""
    id: uuid.UUID
    title: str
    category: str
    due_at: datetime
    owner_id: int
