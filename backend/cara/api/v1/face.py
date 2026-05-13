"""Face recognition REST endpoints (Phase 1).

CRUD for `face_profiles` and the global `face_settings` singleton.
Descriptor endpoints (`POST /face/profiles/{id}/descriptors`, `POST
/face/match`) land in Phase 2 together with the recognition pipeline.

All mutating endpoints write an audit log entry. Admin-only — the
feature is opt-in family-wide and only the household admin manages
identities.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import require_admin
from cara.models.face import FaceDescriptor, FaceProfile, FaceSettings
from cara.models.user import User
from cara.services import audit as audit_svc
from cara.store import get_session


router = APIRouter(prefix="/face", tags=["face"])


# ─── Schemas ───────────────────────────────────────────────────────────


class FaceProfileOut(BaseModel):
    id: UUID
    displayName: str = Field(alias="display_name")
    isChild: bool = Field(alias="is_child")
    matchThreshold: float = Field(alias="match_threshold")
    active: bool
    consentGivenAt: datetime | None = Field(alias="consent_given_at", default=None)
    consentTextVersion: str | None = Field(alias="consent_text_version", default=None)
    descriptorCount: int = Field(alias="descriptor_count", default=0)
    lastRecognizedAt: datetime | None = Field(alias="last_recognized_at", default=None)
    recognitionCount: int = Field(alias="recognition_count", default=0)
    createdAt: datetime = Field(alias="created_at")

    model_config = {"populate_by_name": True, "from_attributes": True}


class FaceProfileCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    is_child: bool = False
    match_threshold: float = Field(default=0.5, ge=0.1, le=1.0)
    consent_text_version: str = Field(min_length=1, max_length=32)


class FaceProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    is_child: bool | None = None
    match_threshold: float | None = Field(default=None, ge=0.1, le=1.0)
    active: bool | None = None


class FaceSettingsOut(BaseModel):
    enabled: bool
    defaultThreshold: float = Field(alias="default_threshold")
    expressionEnabled: bool = Field(alias="expression_enabled")
    ageGenderEnabled: bool = Field(alias="age_gender_enabled")

    model_config = {"populate_by_name": True, "from_attributes": True}


class FaceSettingsUpdate(BaseModel):
    enabled: bool | None = None
    default_threshold: float | None = Field(default=None, ge=0.1, le=1.0)
    expression_enabled: bool | None = None
    age_gender_enabled: bool | None = None


# ─── Helpers ───────────────────────────────────────────────────────────


async def _profile_with_count(session: AsyncSession, profile_id) -> dict | None:
    q = (
        select(
            FaceProfile,
            func.count(FaceDescriptor.id).label("descriptor_count"),
        )
        .outerjoin(FaceDescriptor, FaceDescriptor.profile_id == FaceProfile.id)
        .where(FaceProfile.id == profile_id)
        .group_by(FaceProfile.id)
    )
    row = (await session.execute(q)).one_or_none()
    if row is None:
        return None
    profile, count = row
    return {**profile.__dict__, "descriptor_count": count}


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


# ─── Profile CRUD ─────────────────────────────────────────────────────


@router.get("/profiles", response_model=list[FaceProfileOut])
async def list_profiles(
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[FaceProfileOut]:
    q = (
        select(
            FaceProfile,
            func.count(FaceDescriptor.id).label("descriptor_count"),
        )
        .outerjoin(FaceDescriptor, FaceDescriptor.profile_id == FaceProfile.id)
        .group_by(FaceProfile.id)
        .order_by(FaceProfile.display_name)
    )
    rows = (await session.execute(q)).all()
    out: list[FaceProfileOut] = []
    for profile, count in rows:
        data = {**profile.__dict__, "descriptor_count": count}
        data.pop("_sa_instance_state", None)
        out.append(FaceProfileOut.model_validate(data))
    return out


@router.post(
    "/profiles",
    response_model=FaceProfileOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_profile(
    body: FaceProfileCreate,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> FaceProfileOut:
    # display_name is unique among ACTIVE profiles. The partial index
    # `idx_face_profiles_active_name` would let two inactive copies coexist;
    # check explicitly to give a clean 409.
    existing = (
        await session.execute(
            select(FaceProfile).where(
                FaceProfile.display_name == body.display_name,
                FaceProfile.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"profile '{body.display_name}' already active",
        )

    profile = FaceProfile(
        display_name=body.display_name,
        is_child=body.is_child,
        match_threshold=body.match_threshold,
        consent_given_at=datetime.now(timezone.utc),
        consent_text_version=body.consent_text_version,
        created_by_user_id=admin.id,
    )
    session.add(profile)
    await session.flush()

    await audit_svc.record(
        session,
        actor=admin,
        action="face.profile.create",
        target_kind="face_profile",
        target_id=str(profile.id),
        detail={
            "display_name": body.display_name,
            "is_child": body.is_child,
            "consent_text_version": body.consent_text_version,
        },
        ip=_client_ip(request),
    )
    await session.commit()

    data = {**profile.__dict__, "descriptor_count": 0}
    data.pop("_sa_instance_state", None)
    return FaceProfileOut.model_validate(data)


@router.get("/profiles/{profile_id}", response_model=FaceProfileOut)
async def get_profile(
    profile_id: str,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> FaceProfileOut:
    data = await _profile_with_count(session, profile_id)
    if data is None:
        raise HTTPException(status_code=404, detail="profile not found")
    data.pop("_sa_instance_state", None)
    return FaceProfileOut.model_validate(data)


@router.patch("/profiles/{profile_id}", response_model=FaceProfileOut)
async def update_profile(
    profile_id: str,
    body: FaceProfileUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> FaceProfileOut:
    profile = (
        await session.execute(
            select(FaceProfile).where(FaceProfile.id == profile_id)
        )
    ).scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")

    diff: dict = {}
    if body.display_name is not None and body.display_name != profile.display_name:
        diff["display_name"] = (profile.display_name, body.display_name)
        profile.display_name = body.display_name
    if body.is_child is not None and body.is_child != profile.is_child:
        diff["is_child"] = (profile.is_child, body.is_child)
        profile.is_child = body.is_child
    if (
        body.match_threshold is not None
        and body.match_threshold != profile.match_threshold
    ):
        diff["match_threshold"] = (profile.match_threshold, body.match_threshold)
        profile.match_threshold = body.match_threshold
    if body.active is not None and body.active != profile.active:
        diff["active"] = (profile.active, body.active)
        profile.active = body.active

    if diff:
        await audit_svc.record(
            session,
            actor=admin,
            action="face.profile.update",
            target_kind="face_profile",
            target_id=str(profile.id),
            detail=diff,
            ip=_client_ip(request),
        )
    await session.commit()

    data = await _profile_with_count(session, profile_id)
    assert data is not None
    data.pop("_sa_instance_state", None)
    return FaceProfileOut.model_validate(data)


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(
    profile_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    profile = (
        await session.execute(
            select(FaceProfile).where(FaceProfile.id == profile_id)
        )
    ).scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")

    # Descriptors cascade-delete via FK ON DELETE CASCADE.
    await session.delete(profile)
    await audit_svc.record(
        session,
        actor=admin,
        action="face.profile.delete",
        target_kind="face_profile",
        target_id=str(profile_id),
        detail={"display_name": profile.display_name},
        ip=_client_ip(request),
    )
    await session.commit()


# ─── Settings ─────────────────────────────────────────────────────────


@router.get("/settings", response_model=FaceSettingsOut)
async def get_settings(
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> FaceSettingsOut:
    s = (await session.execute(select(FaceSettings))).scalar_one_or_none()
    if s is None:
        # The migration seeded the singleton row; if it's missing somehow,
        # create a default-disabled one rather than 500-ing.
        s = FaceSettings()
        session.add(s)
        await session.commit()
        await session.refresh(s)
    return FaceSettingsOut.model_validate(s, from_attributes=True)


@router.put("/settings", response_model=FaceSettingsOut)
async def update_settings(
    body: FaceSettingsUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> FaceSettingsOut:
    s = (await session.execute(select(FaceSettings))).scalar_one_or_none()
    if s is None:
        s = FaceSettings()
        session.add(s)
        await session.flush()

    diff: dict = {}
    if body.enabled is not None and body.enabled != s.enabled:
        diff["enabled"] = (s.enabled, body.enabled)
        s.enabled = body.enabled
    if (
        body.default_threshold is not None
        and body.default_threshold != s.default_threshold
    ):
        diff["default_threshold"] = (s.default_threshold, body.default_threshold)
        s.default_threshold = body.default_threshold
    if (
        body.expression_enabled is not None
        and body.expression_enabled != s.expression_enabled
    ):
        diff["expression_enabled"] = (s.expression_enabled, body.expression_enabled)
        s.expression_enabled = body.expression_enabled
    if (
        body.age_gender_enabled is not None
        and body.age_gender_enabled != s.age_gender_enabled
    ):
        diff["age_gender_enabled"] = (s.age_gender_enabled, body.age_gender_enabled)
        s.age_gender_enabled = body.age_gender_enabled

    if diff:
        s.updated_at = datetime.now(timezone.utc)
        await audit_svc.record(
            session,
            actor=admin,
            action="face.settings.update",
            target_kind="face_settings",
            target_id="singleton",
            detail=diff,
            ip=_client_ip(request),
        )
    await session.commit()
    await session.refresh(s)
    return FaceSettingsOut.model_validate(s, from_attributes=True)
