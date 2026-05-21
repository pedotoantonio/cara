"""User ORM model."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from cara.store.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Family role: parent | teen | child | elder | guest. `is_admin` is orthogonal:
    # one user (typically a parent) holds the admin flag for system configuration.
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="parent")
    # Optional birth date — only month+day are used for the birthday reaction;
    # the year is kept just to display "Antonio (38)" style if we ever want it.
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Public Wall surface (`/wall`) — show this user as an owner on the
    # wall-mounted family display? Default true for family roles, false
    # for `guest`. Their color/emoji identify them on chips and the
    # calendar grid; defaults backfilled by migration.
    wall_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    wall_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    wall_emoji: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # Per-user tone override for chat replies. NULL = inherit admin
    # default (admin_settings.tone_preset → "default"). Values must be
    # keys of `_chat_prompt.USER_SELECTABLE_TONES`; the chat layer
    # validates and falls back to "default" on unknown values, so we
    # don't enforce a CHECK constraint here (admin can add new tones
    # without a migration). 24 chars is plenty for the longest key.
    tone_preference: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
