"""Admin endpoints for the Telegram chat ↔ user mappings.

Used by the `/admin/telegram` page so the admin can:
  - list current mappings (shows DB-managed and env-bootstrapped)
  - add a new chat_id ↔ user binding when a family member runs /start
  - rename / toggle notifications / voice per chat
  - send a test message to verify the bot can reach them
  - delete a mapping
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import require_admin
from cara.config import settings
from cara.models import TelegramChatMapping, User
from cara.services import audit as audit_svc
from cara.services import telegram_mappings as tg_map
from cara.store import get_session


router = APIRouter(prefix="/admin/telegram", tags=["admin-telegram"])


class TelegramMappingOut(BaseModel):
    chat_id: int
    user_id: int
    user_email: str
    label: str | None = None
    notifications_enabled: bool
    voice_enabled: bool
    last_active_at: str | None = None
    source: str = "db"  # "db" or "env"


class CreateMappingBody(BaseModel):
    chat_id: int
    user_email: str
    label: str | None = None
    notifications_enabled: bool = True
    voice_enabled: bool = True


class UpdateMappingBody(BaseModel):
    label: str | None = None
    notifications_enabled: bool | None = None
    voice_enabled: bool | None = None
    user_email: str | None = None


class TestMessageBody(BaseModel):
    text: str = "🧪 Test da CARA — il bot raggiunge questo chat correttamente."


def _parse_env_owners() -> set[int]:
    raw = settings.cara_telegram_chat_owners.strip()
    out: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if item.isdigit():
            out.add(int(item))
    return out


def _parse_env_user_map() -> dict[int, str]:
    out: dict[int, str] = {}
    for entry in settings.cara_telegram_chat_user_map.split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        cid, _, email = entry.partition(":")
        if cid.strip().isdigit():
            out[int(cid.strip())] = email.strip()
    return out


@router.get("/mappings", response_model=list[TelegramMappingOut])
async def list_mappings(
    _admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[TelegramMappingOut]:
    """Merged view: DB rows first, then env-bootstrap mappings that
    don't have a DB shadow. The frontend displays them together but
    flags env-only ones as read-only."""
    rows = await tg_map.list_mappings(session)
    out: list[TelegramMappingOut] = []
    seen_chat_ids: set[int] = set()
    # DB rows first.
    for r in rows:
        u = await session.get(User, r.user_id)
        out.append(
            TelegramMappingOut(
                chat_id=r.chat_id,
                user_id=r.user_id,
                user_email=u.email if u else "(utente eliminato)",
                label=r.label,
                notifications_enabled=r.notifications_enabled,
                voice_enabled=r.voice_enabled,
                last_active_at=(
                    r.last_active_at.isoformat() if r.last_active_at else None
                ),
                source="db",
            )
        )
        seen_chat_ids.add(r.chat_id)
    # Env bootstrap fillers.
    env_owners = _parse_env_owners()
    env_map = _parse_env_user_map()
    for cid in env_owners:
        if cid in seen_chat_ids:
            continue
        email = env_map.get(cid)
        if not email:
            continue
        u = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if u is None:
            continue
        out.append(
            TelegramMappingOut(
                chat_id=cid,
                user_id=u.id,
                user_email=u.email,
                label=None,
                notifications_enabled=True,
                voice_enabled=True,
                last_active_at=None,
                source="env",
            )
        )
    return out


@router.post(
    "/mappings", response_model=TelegramMappingOut, status_code=status.HTTP_201_CREATED,
)
async def create_mapping(
    body: CreateMappingBody,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> TelegramMappingOut:
    user = (
        await session.execute(select(User).where(User.email == body.user_email))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"utente {body.user_email} non trovato"
        )
    row = await tg_map.create_or_update(
        session,
        chat_id=body.chat_id,
        user_id=user.id,
        label=body.label,
        notifications_enabled=body.notifications_enabled,
        voice_enabled=body.voice_enabled,
    )
    await audit_svc.record(
        session, actor=admin,
        action=f"telegram.mapping.create[{body.chat_id}]",
        ip=request.client.host if request.client else None,
        detail={"chat_id": body.chat_id, "email": body.user_email},
    )
    await session.commit()
    return TelegramMappingOut(
        chat_id=row.chat_id,
        user_id=row.user_id,
        user_email=user.email,
        label=row.label,
        notifications_enabled=row.notifications_enabled,
        voice_enabled=row.voice_enabled,
        source="db",
    )


@router.patch("/mappings/{chat_id}", response_model=TelegramMappingOut)
async def update_mapping(
    chat_id: int,
    body: UpdateMappingBody,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> TelegramMappingOut:
    user_id: int | None = None
    if body.user_email:
        user = (
            await session.execute(select(User).where(User.email == body.user_email))
        ).scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"utente {body.user_email} non trovato"
            )
        user_id = user.id

    existing = await tg_map.get_by_chat_id(session, chat_id)
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mapping non trovato")
    target_user_id = user_id if user_id is not None else existing.user_id
    row = await tg_map.create_or_update(
        session,
        chat_id=chat_id,
        user_id=target_user_id,
        label=body.label,
        notifications_enabled=body.notifications_enabled,
        voice_enabled=body.voice_enabled,
    )
    await audit_svc.record(
        session, actor=admin,
        action=f"telegram.mapping.update[{chat_id}]",
        ip=request.client.host if request.client else None,
        detail=body.model_dump(exclude_none=True),
    )
    await session.commit()
    u = await session.get(User, row.user_id)
    return TelegramMappingOut(
        chat_id=row.chat_id, user_id=row.user_id,
        user_email=u.email if u else "?",
        label=row.label,
        notifications_enabled=row.notifications_enabled,
        voice_enabled=row.voice_enabled,
        last_active_at=(row.last_active_at.isoformat() if row.last_active_at else None),
        source="db",
    )


@router.delete("/mappings/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mapping(
    chat_id: int,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    ok = await tg_map.delete(session, chat_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mapping non trovato")
    await audit_svc.record(
        session, actor=admin,
        action=f"telegram.mapping.delete[{chat_id}]",
        ip=request.client.host if request.client else None,
        detail={"chat_id": chat_id},
    )
    await session.commit()


@router.post("/mappings/{chat_id}/test")
async def send_test(
    chat_id: int,
    body: TestMessageBody,
    _admin: User = Depends(require_admin),  # noqa: B008
) -> dict[str, Any]:
    """Send a test message to a single chat — quick way to verify
    that the user actually pressed /start on the bot."""
    from cara.integrations import telegram as _tg  # noqa: PLC0415

    if _tg._application is None:  # noqa: SLF001
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Telegram bot non avviato (CARA_TELEGRAM_BOT_TOKEN mancante?)",
        )
    bot = _tg._application.bot  # noqa: SLF001
    try:
        msg = await bot.send_message(
            chat_id=chat_id, text=body.text, parse_mode="HTML",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"telegram error: {exc}"
        ) from exc
    return {"ok": True, "message_id": msg.message_id}
