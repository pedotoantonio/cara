"""Auth endpoints: register, login, refresh, /me."""

from __future__ import annotations

import ipaddress

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
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

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# CIDRs that are considered "trusted" for the LAN auto-login endpoint
# below. Anyone with an IP in these ranges gets a JWT for the first
# admin without typing a password — the assumption is "physical access
# to the home Wi-Fi or the WireGuard VPN is enough to identify the
# user as family". Public internet (Cloudflare Tunnel, port forward)
# does NOT match these and still needs full credential auth.
_LAN_AUTO_LOGIN_CIDRS = [
    ipaddress.ip_network("192.168.1.0/24"),    # home LAN
    ipaddress.ip_network("10.8.0.0/24"),        # WireGuard VPN
    ipaddress.ip_network("127.0.0.0/8"),        # localhost (dev / tests)
]
# Hops we trust to set X-Forwarded-For correctly (nginx-proxy and
# cara-frontend internal proxy). The header is only honoured when the
# direct request originates from one of these.
_TRUSTED_PROXIES = {
    "172.31.0.5",   # nginx-proxy
    "172.31.0.20",  # cara-frontend nginx
    "127.0.0.1",
}


def _client_ip(request: Request) -> str | None:
    """Resolve the client's real IP, walking X-Forwarded-For only when
    the direct hop is a trusted CARA proxy. Returns None if we can't
    determine a usable IP."""
    direct = request.client.host if request.client else None
    if direct and direct in _TRUSTED_PROXIES:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            # First IP in the chain = original client.
            for candidate in xff.split(","):
                candidate = candidate.strip()
                if candidate:
                    return candidate
    return direct


def _ip_is_lan(ip_str: str | None) -> bool:
    if not ip_str:
        return False
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(ip in net for net in _LAN_AUTO_LOGIN_CIDRS)


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


@router.post("/lan-login", response_model=TokenPair)
async def lan_login(
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> TokenPair:
    """Password-less login for clients on the home LAN or WireGuard VPN.

    Frontend calls this on boot when no token is in localStorage. If
    the client IP is in `192.168.1.0/24`, `10.8.0.0/24`, or `127.0.0.0/8`
    we issue a JWT for the first admin user — same payload the regular
    login emits. Public-internet access (Cloudflare Tunnel, port
    forward, anyone outside the trusted CIDRs) gets a 403 and falls
    through to the normal login form.

    Disable via admin setting `lan_auto_login_enabled = false` if you
    later want to enforce credential auth even from inside the house.
    """
    from cara.services import admin_settings as admin_svc  # noqa: PLC0415

    enabled = await admin_svc.get(session, "lan_auto_login_enabled")
    if enabled is False:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "LAN auto-login disabled by admin"
        )

    ip = _client_ip(request)
    if not _ip_is_lan(ip):
        log.info("auth.lan_login.rejected_non_lan", client_ip=ip)
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "LAN auto-login not allowed from this IP"
        )

    # First active admin in the DB gets the auto-login token. Family
    # accounts created later don't get this privilege automatically.
    admin = (
        await session.execute(
            select(User)
            .where(User.is_admin.is_(True), User.is_active.is_(True))
            .order_by(User.id.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if admin is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no admin user configured")

    log.info("auth.lan_login.granted", client_ip=ip, user_id=admin.id, email=admin.email)
    return TokenPair(
        access_token=auth_svc.create_access_token(
            admin.id, extra={"is_admin": admin.is_admin}
        ),
        refresh_token=auth_svc.create_refresh_token(admin.id),
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
