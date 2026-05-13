"""Face recognition REST endpoints.

Profiles + descriptors + global settings. The browser computes 128-D
descriptors via face-api.js and ships them here; the backend stores
them and serves them back to new devices for offline local matching.

All mutating endpoints write an audit log entry. Admin-only — the
feature is opt-in family-wide and only the household admin manages
identities.

Retention: max 30 descriptors per profile. When the cap is exceeded the
oldest `source='continuous'` rows are pruned first; `source='enrollment'`
rows (the 5 wizard captures) are never auto-deleted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import require_admin
from cara.models.face import FaceDescriptor, FaceProfile, FaceSettings
from cara.models.user import User
from cara.services import audit as audit_svc
from cara.store import get_session


MAX_DESCRIPTORS_PER_PROFILE = 30


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


class DescriptorIn(BaseModel):
    """One descriptor to persist for a profile."""

    descriptor: list[float] = Field(min_length=128, max_length=128)
    source: str = Field(pattern="^(enrollment|continuous)$")
    quality: float | None = Field(default=None, ge=0.0, le=1.0)


class DescriptorsBulkIn(BaseModel):
    items: list[DescriptorIn] = Field(min_length=1, max_length=10)


class DescriptorOut(BaseModel):
    id: UUID
    profileId: UUID = Field(alias="profile_id")
    descriptor: list[float]
    source: str
    quality: float | None = None
    createdAt: datetime = Field(alias="created_at")

    model_config = {"populate_by_name": True, "from_attributes": True}


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


# ─── Descriptors ──────────────────────────────────────────────────────


async def _prune_excess_descriptors(
    session: AsyncSession, profile_id: UUID, keep_recent: int
) -> int:
    """Trim continuous descriptors so the profile stays under the cap.

    Returns the number of rows deleted. Enrollment descriptors are
    preserved unconditionally — they are the user-curated baseline.
    """
    total = (
        await session.execute(
            select(func.count(FaceDescriptor.id)).where(
                FaceDescriptor.profile_id == profile_id
            )
        )
    ).scalar_one()
    if total <= keep_recent:
        return 0

    excess = total - keep_recent

    # Find the `excess` oldest continuous rows.
    to_drop = (
        (
            await session.execute(
                select(FaceDescriptor.id)
                .where(
                    FaceDescriptor.profile_id == profile_id,
                    FaceDescriptor.source == "continuous",
                )
                .order_by(FaceDescriptor.created_at.asc())
                .limit(excess)
            )
        )
        .scalars()
        .all()
    )
    if not to_drop:
        return 0

    await session.execute(
        delete(FaceDescriptor).where(FaceDescriptor.id.in_(to_drop))
    )
    return len(to_drop)


@router.post(
    "/profiles/{profile_id}/descriptors",
    response_model=list[DescriptorOut],
    status_code=status.HTTP_201_CREATED,
)
async def add_descriptors(
    profile_id: UUID,
    body: DescriptorsBulkIn,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[DescriptorOut]:
    profile = (
        await session.execute(select(FaceProfile).where(FaceProfile.id == profile_id))
    ).scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")

    new_rows = [
        FaceDescriptor(
            profile_id=profile_id,
            descriptor=item.descriptor,
            source=item.source,
            quality=item.quality,
        )
        for item in body.items
    ]
    for r in new_rows:
        session.add(r)
    await session.flush()

    pruned = await _prune_excess_descriptors(
        session, profile_id, MAX_DESCRIPTORS_PER_PROFILE
    )

    await audit_svc.record(
        session,
        actor=admin,
        action="face.descriptor.add",
        target_kind="face_profile",
        target_id=str(profile_id),
        detail={
            "added": len(new_rows),
            "sources": sorted({i.source for i in body.items}),
            "pruned": pruned,
        },
        ip=_client_ip(request),
    )
    await session.commit()

    out: list[DescriptorOut] = []
    for r in new_rows:
        await session.refresh(r)
        out.append(
            DescriptorOut.model_validate(
                {
                    "id": r.id,
                    "profile_id": r.profile_id,
                    "descriptor": list(r.descriptor),
                    "source": r.source,
                    "quality": r.quality,
                    "created_at": r.created_at,
                }
            )
        )
    return out


@router.get(
    "/profiles/{profile_id}/descriptors",
    response_model=list[DescriptorOut],
)
async def list_descriptors(
    profile_id: UUID,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[DescriptorOut]:
    profile = (
        await session.execute(select(FaceProfile).where(FaceProfile.id == profile_id))
    ).scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")

    rows = (
        (
            await session.execute(
                select(FaceDescriptor)
                .where(FaceDescriptor.profile_id == profile_id)
                .order_by(FaceDescriptor.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        DescriptorOut.model_validate(
            {
                "id": r.id,
                "profile_id": r.profile_id,
                "descriptor": list(r.descriptor),
                "source": r.source,
                "quality": r.quality,
                "created_at": r.created_at,
            }
        )
        for r in rows
    ]


# ─── Server-side match (optional, for new devices without a local cache) ──


class MatchIn(BaseModel):
    descriptor: list[float] = Field(min_length=128, max_length=128)


class MatchHit(BaseModel):
    profileId: UUID = Field(alias="profile_id")
    displayName: str = Field(alias="display_name")
    isChild: bool = Field(alias="is_child")
    distance: float
    matchedDescriptorId: UUID = Field(alias="matched_descriptor_id")

    model_config = {"populate_by_name": True, "from_attributes": True}


class MatchOut(BaseModel):
    match: MatchHit | None


@router.post("/match", response_model=MatchOut)
async def server_match(
    body: MatchIn,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> MatchOut:
    """Server-side nearest-neighbor over pgvector.

    Useful for a fresh device that hasn't downloaded the descriptor cache
    yet, or for double-checking a client-side match before triggering
    high-stakes actions. Returns the closest profile that beats its own
    threshold, or `None`.
    """
    # The L2 (euclidean) distance operator in pgvector is `<->`. We use
    # the cosine HNSW index for `<=>` but for face descriptors trained
    # on euclidean the right metric is L2; query unindexed for now.
    sql = (
        select(
            FaceDescriptor.id,
            FaceDescriptor.profile_id,
            FaceProfile.display_name,
            FaceProfile.is_child,
            FaceProfile.match_threshold,
            FaceDescriptor.descriptor.l2_distance(body.descriptor).label("distance"),
        )
        .join(FaceProfile, FaceProfile.id == FaceDescriptor.profile_id)
        .where(FaceProfile.active.is_(True))
        .order_by("distance")
        .limit(2)
    )
    rows = (await session.execute(sql)).all()
    if not rows:
        return MatchOut(match=None)

    best = rows[0]
    second_dist = rows[1].distance if len(rows) > 1 else float("inf")

    # Same ambiguity guard the client uses.
    if best.distance > best.match_threshold:
        return MatchOut(match=None)
    if second_dist - best.distance < 0.05 and second_dist < float("inf"):
        # Second-best is from a different profile? Then it's ambiguous.
        second_pid = rows[1].profile_id if len(rows) > 1 else None
        if second_pid is not None and second_pid != best.profile_id:
            return MatchOut(match=None)

    # Bump usage stats — non-blocking, audit-free since this isn't a mod.
    await session.execute(
        FaceProfile.__table__.update()
        .where(FaceProfile.id == best.profile_id)
        .values(
            recognition_count=FaceProfile.recognition_count + 1,
            last_recognized_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()

    return MatchOut(
        match=MatchHit.model_validate(
            {
                "profile_id": best.profile_id,
                "display_name": best.display_name,
                "is_child": best.is_child,
                "distance": float(best.distance),
                "matched_descriptor_id": best.id,
            }
        )
    )
