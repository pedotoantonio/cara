"""Admin endpoints for device alias overrides (Step 5.4).

  GET    /api/v1/admin/device-aliases?entity_id=
  POST   /api/v1/admin/device-aliases       create alias
  DELETE /api/v1/admin/device-aliases/{id}

All admin-only. The smart-home NLU resolver consumes the merged list
(auto from friendly_name + admin overrides) on every chat turn, so
adding an alias takes effect immediately.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import require_admin
from cara.models.user import User
from cara.services import device_aliases as svc
from cara.store import get_session


router = APIRouter(prefix="/admin/device-aliases", tags=["admin-smarthome"])


class DeviceAliasOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    entity_id: str
    alias: str
    area: str | None
    source_user_id: int | None


class DeviceAliasCreate(BaseModel):
    entity_id: str = Field(min_length=3, max_length=120)
    alias: str = Field(min_length=1, max_length=120)
    area: str | None = Field(default=None, max_length=80)


@router.get("", response_model=list[DeviceAliasOut])
async def list_aliases(
    entity_id: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=200, ge=1, le=500),
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[DeviceAliasOut]:
    rows = await svc.list_aliases(session, entity_id=entity_id, limit=limit)
    return [DeviceAliasOut.model_validate(r) for r in rows]


@router.post("", response_model=DeviceAliasOut, status_code=status.HTTP_201_CREATED)
async def create_alias(
    body: DeviceAliasCreate,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DeviceAliasOut:
    try:
        row = await svc.create_alias(
            session,
            entity_id=body.entity_id,
            alias=body.alias,
            area=body.area,
            source_user_id=admin.id,
            commit=True,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        # Most likely the unique constraint (entity_id, alias) collision.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "alias already exists for this entity",
        ) from exc
    return DeviceAliasOut.model_validate(row)


@router.delete("/{alias_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alias(
    alias_id: int,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    ok = await svc.delete_alias(session, alias_id, commit=True)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "alias not found")
