"""OAuth endpoints for Google integrations.

Flow:
  POST /api/v1/oauth/google/authorize?scope_set=calendar:rw
       (auth required)            → returns {"authorize_url": "..."}
                                     frontend then window.location to it.
  GET  /api/v1/oauth/google/callback?code=...&state=...
       (no auth — the user comes from accounts.google.com)
       → exchanges code for tokens → redirects browser to /me/integrazioni
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.integrations import google_oauth
from cara.models.user import User
from cara.store import get_session


log = structlog.get_logger(__name__)
router = APIRouter(prefix="/oauth", tags=["oauth"])


@router.get("/google/status")
async def google_status() -> dict:
    """Cheap health probe — used by the UI to hide the connect buttons
    when the admin hasn't configured the OAuth client."""
    return {"available": google_oauth.is_available()}


@router.post("/google/authorize")
async def google_authorize(
    scope_set: str = Query(..., regex="^(calendar:rw|gmail:ro)$"),
    user: User = Depends(get_current_user),  # noqa: B008
) -> dict:
    if not google_oauth.is_available():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google integrations not configured (missing client_id/secret)",
        )
    try:
        url, state = google_oauth.build_authorize_url(
            user_id=user.id, scope_set=scope_set,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"authorize_url": url, "state": state}


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RedirectResponse:
    """Browser-facing callback. Always redirects to /me/integrazioni
    with a query string indicating success or failure."""
    if not google_oauth.is_available():
        return RedirectResponse(url="/me/integrazioni?google=unavailable")
    try:
        cred = await google_oauth.handle_callback(session, code=code, state=state)
    except Exception as exc:  # noqa: BLE001
        log.warning("oauth.callback_failed", error=str(exc))
        return RedirectResponse(
            url=f"/me/integrazioni?google=error&detail={exc}",
            status_code=302,
        )
    return RedirectResponse(
        url=f"/me/integrazioni?google=connected&scope={cred.scope_set}",
        status_code=302,
    )
