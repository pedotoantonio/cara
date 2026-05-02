"""Auth endpoints: register, login, refresh, /me."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.models.user import User
from cara.schemas.auth import (
    PasswordChange,
    RefreshRequest,
    TokenPair,
    UserLogin,
    UserOut,
    UserRegister,
    UserUpdate,
)
from cara.services import auth as auth_svc
from cara.store import get_session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    body: UserRegister,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> UserOut:
    existing = await auth_svc.get_user_by_email(session, body.email)
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")
    user = await auth_svc.create_user(
        session, email=body.email, password=body.password, full_name=body.full_name
    )
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenPair)
async def login(
    body: UserLogin,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> TokenPair:
    user = await auth_svc.authenticate(session, body.email, body.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    return TokenPair(
        access_token=auth_svc.create_access_token(user.id, extra={"is_admin": user.is_admin}),
        refresh_token=auth_svc.create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    body: RefreshRequest,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> TokenPair:
    try:
        payload = auth_svc.decode_token(body.refresh_token)
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    if payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong token type")
    user_id = int(payload["sub"])
    user = await auth_svc.get_user_by_id(session, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user disabled or missing")
    return TokenPair(
        access_token=auth_svc.create_access_token(user.id, extra={"is_admin": user.is_admin}),
        refresh_token=auth_svc.create_refresh_token(user.id),
    )


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:  # noqa: B008
    return UserOut.model_validate(user)


@router.patch("/me", response_model=UserOut)
async def update_me(
    body: UserUpdate,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> UserOut:
    fields = body.model_fields_set
    if body.full_name is not None:
        user.full_name = body.full_name.strip() or None
    if body.role is not None:
        if user.role in ("child", "teen") and body.role in ("parent", "elder"):
            pass
        else:
            user.role = body.role
    if "birth_date" in fields:
        user.birth_date = body.birth_date  # may be None to clear
    session.add(user)
    await session.flush()
    return UserOut.model_validate(user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChange,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    if not auth_svc.verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "current password incorrect")
    user.password_hash = auth_svc.hash_password(body.new_password)
    session.add(user)
    await session.flush()
