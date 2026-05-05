"""Schemas for chat completion endpoints."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    max_new_tokens: int | None = Field(default=None, ge=1, le=2048)
    # The runtime ignores per-request sampling overrides for now (set at init).
    # Kept in the schema so the wire format is forward-compatible.
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_k: int | None = Field(default=None, ge=1, le=200)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    # Files attached to the most recent user message. Backend resolves IDs
    # against the user's owned files and prepends extracted text to the prompt.
    file_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)
    # Opt-in cloud LLM (Anthropic Haiku) for this single turn. Effective
    # only if the admin flag `cloud_llm_enabled` is True. The caller
    # provides this when the user clicks a "Risposta migliore" button.
    prefer_cloud: bool = Field(default=False)


class ChatStats(BaseModel):
    tokens: int
    first_token_seconds: float
    total_seconds: float
    tokens_per_second: float
