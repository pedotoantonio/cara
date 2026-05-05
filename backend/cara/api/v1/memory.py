"""Memory endpoints — semantic facts CRUD + extraction + GDPR export.

What's exposed:

  GET    /api/v1/memory/facts                  (current user's facts)
  POST   /api/v1/memory/facts                  (manual fact via pin/UI)
  PATCH  /api/v1/memory/facts/{id}             (update text / confidence / active)
  DELETE /api/v1/memory/facts/{id}             (deactivate, not destroy — keeps audit)
  POST   /api/v1/memory/facts/extract          (run pattern detector on a message)
  GET    /api/v1/memory/export                 (GDPR JSON export of THIS user)
  DELETE /api/v1/memory/purge                  (hard delete THIS user's facts)

All routes are scoped to the authenticated user — there is no way to
read another family member's facts via this endpoint, by design. Admin
visibility into someone else's memory uses a future
`/api/v1/admin/memory/<user_id>` route gated by `require_admin`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.learning import semantic
from cara.models.fact import (
    FACT_SOURCE_EXPLICIT,
    FACT_SOURCE_PIN,
    Fact,
)
from cara.models.user import User
from cara.schemas.memory import (
    ExtractFactsRequest,
    FactCreate,
    FactOut,
    FactPatch,
)
from cara.store import get_session


router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/facts", response_model=list[FactOut])
async def list_my_facts(
    active_only: bool = True,
    fact_type: str | None = None,
    limit: int = 100,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[FactOut]:
    types = [fact_type] if fact_type else None
    rows = await semantic.list_facts(
        session,
        user_id=user.id,
        types=types,
        active_only=active_only,
        limit=max(1, min(limit, 500)),
    )
    return [FactOut.model_validate(r) for r in rows]


@router.post(
    "/facts", response_model=FactOut, status_code=status.HTTP_201_CREATED,
)
async def create_my_fact(
    body: FactCreate,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> FactOut:
    fact = await semantic.save_fact(
        session,
        user_id=user.id,
        text=body.text.strip(),
        fact_type=body.type,
        source=FACT_SOURCE_PIN,
        confidence=body.confidence,
        commit=True,
    )
    return FactOut.model_validate(fact)


@router.patch("/facts/{fact_id}", response_model=FactOut)
async def patch_my_fact(
    fact_id: int,
    body: FactPatch,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> FactOut:
    fact = (await session.execute(
        select(Fact).where(Fact.id == fact_id, Fact.user_id == user.id)
    )).scalar_one_or_none()
    if fact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fact not found")

    if body.text is not None:
        fact.text = body.text.strip()
        # Manual edit by the user is treated as an explicit confirmation.
        fact.source = FACT_SOURCE_EXPLICIT
    if body.confidence is not None:
        fact.confidence = body.confidence
    if body.active is not None:
        fact.active = body.active

    await session.commit()
    await session.refresh(fact)
    return FactOut.model_validate(fact)


@router.delete("/facts/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def soft_delete_my_fact(
    fact_id: int,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    """Soft delete: sets active=False so the audit trail is preserved.

    For a real GDPR purge use `DELETE /memory/purge` (drops every fact).
    """
    # Ownership check + deactivate.
    fact = (await session.execute(
        select(Fact).where(Fact.id == fact_id, Fact.user_id == user.id)
    )).scalar_one_or_none()
    if fact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fact not found")
    fact.active = False
    await session.commit()


@router.post("/facts/extract")
async def extract_facts_from_message(
    body: ExtractFactsRequest,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """Run the pattern detector on `message`. Returns proposed facts;
    optionally persists them when `save=true`."""
    proposals = semantic.detect_facts(body.message)
    if body.save and proposals:
        saved = await semantic.save_facts_from_message(
            session, user_id=user.id, message=body.message, commit=True,
        )
        return {
            "proposals": [
                {
                    "fact_text": p.fact_text, "fact_type": p.fact_type,
                    "confidence": p.confidence, "source": p.source,
                }
                for p in proposals
            ],
            "saved_ids": [s.id for s in saved],
        }
    return {
        "proposals": [
            {
                "fact_text": p.fact_text, "fact_type": p.fact_type,
                "confidence": p.confidence, "source": p.source,
            }
            for p in proposals
        ],
        "saved_ids": [],
    }


@router.get("/export")
async def export_my_memory(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """GDPR-style JSON export of all this user's facts."""
    rows = await semantic.list_facts(
        session, user_id=user.id, active_only=False, limit=10_000,
    )
    return {
        "user_id": user.id,
        "email": user.email,
        "exported_at_utc": rows[0].first_seen.isoformat() if rows else None,
        "count": len(rows),
        "facts": [FactOut.model_validate(r).model_dump(mode="json") for r in rows],
    }


@router.delete("/purge", status_code=status.HTTP_200_OK)
async def purge_my_memory(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, int]:
    """Hard delete every fact owned by THIS user.

    Family-wide facts (`user_id IS NULL`) are NOT touched — those affect
    other family members and require an admin-level purge.
    """
    result = await session.execute(
        delete(Fact).where(Fact.user_id == user.id)
    )
    deleted = result.rowcount or 0
    await session.commit()
    return {"deleted": deleted}
