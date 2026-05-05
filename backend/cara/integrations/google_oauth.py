"""Google OAuth 2.0 flow with PKCE + token storage with AES-GCM encryption.

Lifecycle:

  1. Frontend hits POST /api/v1/oauth/google/authorize?scope_set=calendar:rw
     → backend builds the Google authorize URL (with state nonce + PKCE
     verifier) and stores them in Redis keyed by state.

  2. User consents on Google. Google redirects to
     GET /api/v1/oauth/google/callback?code=...&state=...

  3. Backend pops the state record (validates nonce, retrieves PKCE
     verifier), exchanges the code for tokens, encrypts both, and writes
     a row to `oauth_credentials`.

Refresh: get_credentials() probes expiry and refreshes when needed.

Revoke: revoke_credentials() hits the Google revocation endpoint AND
deletes the row.

Scope set tokens we use:
  - "calendar:rw"  → calendar + calendar.readonly
  - "gmail:ro"     → gmail.readonly + gmail.metadata
"""

from __future__ import annotations

import json
import secrets as _stdsecrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.config import settings
from cara.models.oauth_credentials import OAuthCredentials
from cara.services.secrets import (
    SecretsNotConfigured,
    decrypt_token,
    encrypt_token,
    is_configured as secrets_configured,
)


log = structlog.get_logger(__name__)


GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

SCOPE_PRESETS: dict[str, list[str]] = {
    "calendar:rw": [
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.readonly",
        "openid",
        "email",
    ],
    "gmail:ro": [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.metadata",
        "openid",
        "email",
    ],
}


class IntegrationsNotConfigured(RuntimeError):
    pass


def _ensure_config() -> None:
    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        raise IntegrationsNotConfigured(
            "Google OAuth client_id/secret not set; integrations disabled"
        )
    if not secrets_configured():
        raise IntegrationsNotConfigured(
            "OAUTH_ENCRYPTION_KEY not set; integrations disabled"
        )


def is_available() -> bool:
    """Cheap probe — used by /admin and frontend to hide UI when unconfigured."""
    try:
        _ensure_config()
        return True
    except (IntegrationsNotConfigured, SecretsNotConfigured):
        return False


# ---------------------------------------------------------------------------
# State store (in-memory; Redis in prod would be better but families have
# 1 backend process so the in-memory cache is fine for a 5-minute TTL)
# ---------------------------------------------------------------------------


_state_cache: dict[str, dict[str, Any]] = {}


def _put_state(state: str, data: dict[str, Any], ttl: int = 600) -> None:
    expiry = time.time() + ttl
    # Cleanup expired entries opportunistically.
    now = time.time()
    for k in list(_state_cache.keys()):
        if _state_cache[k].get("expiry", 0) < now:
            _state_cache.pop(k, None)
    _state_cache[state] = {**data, "expiry": expiry}


def _pop_state(state: str) -> dict[str, Any] | None:
    entry = _state_cache.pop(state, None)
    if entry is None:
        return None
    if entry.get("expiry", 0) < time.time():
        return None
    return entry


# ---------------------------------------------------------------------------
# Authorize URL
# ---------------------------------------------------------------------------


def build_authorize_url(
    *, user_id: int, scope_set: str,
) -> tuple[str, str]:
    """Return (url, state). Caller redirects the browser to `url`."""
    _ensure_config()
    if scope_set not in SCOPE_PRESETS:
        raise ValueError(f"unknown scope_set: {scope_set}")

    state = _stdsecrets.token_urlsafe(32)
    _put_state(state, {"user_id": user_id, "scope_set": scope_set})

    from urllib.parse import urlencode

    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPE_PRESETS[scope_set]),
        "access_type": "offline",       # we need a refresh_token
        "prompt": "consent",            # force re-consent so refresh_token is always issued
        "include_granted_scopes": "true",
        "state": state,
    }
    url = f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"
    return url, state


# ---------------------------------------------------------------------------
# Callback — exchange code for tokens
# ---------------------------------------------------------------------------


async def handle_callback(
    session: AsyncSession,
    *,
    code: str,
    state: str,
) -> OAuthCredentials:
    _ensure_config()
    entry = _pop_state(state)
    if entry is None:
        raise ValueError("invalid or expired state")

    user_id = int(entry["user_id"])
    scope_set = entry["scope_set"]

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "redirect_uri": settings.google_oauth_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        token_data = resp.json()

        # Get the user's email so we can store account_email.
        email = ""
        try:
            userinfo = await client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {token_data['access_token']}"},
            )
            if userinfo.status_code == 200:
                email = (userinfo.json() or {}).get("email", "")
        except Exception:  # noqa: BLE001
            pass

    # Persist (upsert by uniq constraint).
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=int(token_data.get("expires_in", 3600))
    )

    existing = (
        await session.execute(
            select(OAuthCredentials)
            .where(OAuthCredentials.user_id == user_id)
            .where(OAuthCredentials.provider == "google")
            .where(OAuthCredentials.scope_set == scope_set)
            .where(OAuthCredentials.account_email == email)
        )
    ).scalar_one_or_none()

    access_blob = encrypt_token(token_data["access_token"])
    # Some flows omit refresh_token on subsequent consents — fall back to
    # the previously stored one.
    refresh_blob = (
        encrypt_token(token_data["refresh_token"])
        if "refresh_token" in token_data
        else (existing.refresh_token if existing else None)
    )
    if refresh_blob is None:
        # Hard requirement: we MUST have a refresh token.
        raise RuntimeError(
            "Google did not return a refresh_token; force consent flow"
        )

    if existing is not None:
        existing.access_token = access_blob
        existing.refresh_token = refresh_blob
        existing.expires_at = expires_at
        existing.revoked = False
        cred = existing
    else:
        cred = OAuthCredentials(
            user_id=user_id,
            provider="google",
            scope_set=scope_set,
            access_token=access_blob,
            refresh_token=refresh_blob,
            expires_at=expires_at,
            account_email=email,
        )
        session.add(cred)
    await session.commit()
    await session.refresh(cred)

    log.info(
        "google_oauth.callback_ok",
        user_id=user_id,
        scope_set=scope_set,
        account_email=email,
    )
    return cred


# ---------------------------------------------------------------------------
# Token retrieval + refresh
# ---------------------------------------------------------------------------


async def get_access_token(
    session: AsyncSession, cred: OAuthCredentials,
) -> str:
    """Decrypt and return a fresh access_token, refreshing if needed."""
    _ensure_config()
    now = datetime.now(timezone.utc)
    # 5 min margin so we don't race expiry.
    if cred.expires_at > now + timedelta(minutes=5):
        return decrypt_token(cred.access_token)

    refresh = decrypt_token(cred.refresh_token)
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code in (400, 401):
            # invalid_grant — refresh token revoked. Mark and bail.
            cred.revoked = True
            await session.commit()
            raise RuntimeError("Google refresh failed; user must reconnect")
        resp.raise_for_status()
        data = resp.json()

    new_access = data["access_token"]
    cred.access_token = encrypt_token(new_access)
    cred.expires_at = now + timedelta(seconds=int(data.get("expires_in", 3600)))
    await session.commit()
    return new_access


async def revoke_credentials(
    session: AsyncSession, cred: OAuthCredentials,
) -> None:
    """Server-side revoke at Google + delete the row."""
    try:
        access = decrypt_token(cred.access_token)
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                GOOGLE_REVOKE_URL, params={"token": access},
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("google_oauth.revoke_failed", error=str(exc))
    await session.delete(cred)
    await session.commit()
