"""Admin endpoints for TTS pronunciation overrides (Step 1.2).

The shipped `anglicisms.yaml` covers ~300 common loanwords. Each family
will discover its own corner cases (dialect words the kids invent,
proprietary brand names, surnames). This admin endpoint lets the family
add to / override the shipped dictionary at runtime, persisted in
`admin_settings["tts_user_overrides"]`.

  GET    /api/v1/admin/tts/overrides           current dict
  PUT    /api/v1/admin/tts/overrides           replace whole dict
  PATCH  /api/v1/admin/tts/overrides           merge in new entries
  DELETE /api/v1/admin/tts/overrides/{word}    remove one entry
  POST   /api/v1/admin/tts/preview             dry-run normalisation

A successful write also re-applies the merged dict to the process-wide
`TTSNormalizer` so the next TTS request reflects the change without
restarting the backend.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cara.ai.tts.normalizer import get_global_normalizer
from cara.api.deps import require_admin
from cara.models.user import User
from cara.services import admin_settings as setting_svc
from cara.services import audit as audit_svc
from cara.store import get_session


router = APIRouter(prefix="/admin/tts", tags=["admin-tts"])


_KEY = "tts_user_overrides"


# Validation: the english side ("weekend") must be alphanumeric +
# spaces / dots / apostrophes — refusing arbitrary regex / control
# chars protects the runtime regex compiler in TTSNormalizer.
_WORD_RE = re.compile(r"^[\w\s.'-]{1,80}$", re.UNICODE)


def _validate_word(word: str) -> None:
    if not _WORD_RE.match(word.strip()):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"invalid word: {word!r}",
        )


# ---------------------------------------------------------------- schemas


class OverridesPut(BaseModel):
    """Whole-dict replace."""
    overrides: dict[str, str] = Field(default_factory=dict)


class OverridesPatch(BaseModel):
    """Partial merge — only the keys present are added/updated."""
    overrides: dict[str, str] = Field(default_factory=dict)


class PreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


# ---------------------------------------------------------------- handlers


async def _read_overrides(session: AsyncSession) -> dict[str, str]:
    raw = await setting_svc.get(session, _KEY)
    if not isinstance(raw, dict):
        return {}
    # Defensive: skip non-string keys/values that may have leaked in.
    out: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, str):
            out[k.strip()] = v.strip()
    return out


async def _persist_and_apply(
    session: AsyncSession, overrides: dict[str, str], *, admin_user_id: int,
) -> dict[str, str]:
    """Persist the dict + push it into the process-wide normalizer."""
    await setting_svc.set(session, _KEY, overrides, actor_user_id=admin_user_id)
    # Hot-swap: the next TTS call uses the new dict.
    get_global_normalizer().set_user_overrides(overrides)
    return overrides


@router.get("/overrides")
async def get_overrides(
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    overrides = await _read_overrides(session)
    return {
        "count": len(overrides),
        "overrides": overrides,
    }


@router.put("/overrides")
async def put_overrides(
    body: OverridesPut,
    request_obj=None,  # request injected via star-arg pattern below
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """Replace the full overrides dict atomically."""
    cleaned: dict[str, str] = {}
    for k, v in body.overrides.items():
        _validate_word(k)
        if not isinstance(v, str) or len(v) > 80:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"value for {k!r} must be a string ≤80 chars",
            )
        cleaned[k.strip().lower()] = v.strip()

    final = await _persist_and_apply(session, cleaned, admin_user_id=admin.id)
    await audit_svc.record(
        session, actor=admin, action="tts.overrides.put",
        target_kind="admin_settings",
        detail={"count": len(final)},
    )
    return {"count": len(final), "overrides": final}


@router.patch("/overrides")
async def patch_overrides(
    body: OverridesPatch,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """Merge the supplied entries into the existing dict.

    Empty-string value deletes the entry on the merge layer (consistent
    with TTSNormalizer.set_user_overrides semantics).
    """
    current = await _read_overrides(session)
    for k, v in body.overrides.items():
        _validate_word(k)
        if not isinstance(v, str) or len(v) > 80:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"value for {k!r} must be a string ≤80 chars",
            )
        if v.strip() == "":
            current.pop(k.strip().lower(), None)
        else:
            current[k.strip().lower()] = v.strip()

    final = await _persist_and_apply(session, current, admin_user_id=admin.id)
    await audit_svc.record(
        session, actor=admin, action="tts.overrides.patch",
        target_kind="admin_settings",
        detail={"changed": list(body.overrides.keys()), "count": len(final)},
    )
    return {"count": len(final), "overrides": final}


@router.delete(
    "/overrides/{word}", status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_override(
    word: str,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    _validate_word(word)
    current = await _read_overrides(session)
    if current.pop(word.strip().lower(), None) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "word not in overrides")
    await _persist_and_apply(session, current, admin_user_id=admin.id)
    await audit_svc.record(
        session, actor=admin, action="tts.overrides.delete",
        target_kind="admin_settings", detail={"word": word.strip().lower()},
    )


@router.post("/preview")
async def preview_normalisation(
    body: PreviewRequest,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """Apply the current dict (base + user overrides) to `text` and
    return the normalised form. Lets the admin verify a tweak without
    actually triggering a TTS call."""
    # Sync overrides from DB first so the preview reflects what's saved
    # rather than what the singleton happens to hold (relevant if
    # another worker process changed it).
    overrides = await _read_overrides(session)
    nlz = get_global_normalizer()
    nlz.set_user_overrides(overrides)
    return {
        "input": body.text,
        "output": nlz.normalize(body.text),
        "active_overrides": nlz.size,
    }
