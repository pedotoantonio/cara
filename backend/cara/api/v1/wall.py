"""Wall surface — public read-only API for a wall-mounted family display.

Access model:

    Anyone on the LAN (192.168.1.0/24), WireGuard VPN (10.8.0.0/24), or
    localhost can hit these endpoints. No JWT required. Any external
    request returns 403. The Wall display is treated as a kiosk that
    sits on a wall in the home — physical access to the network is the
    auth boundary.

Data exposed is intentionally compact (titles, owners, due dates) — no
chat content, file blobs, descriptions, or PII beyond names. Per-record
opt-out via `wall_visible` columns on `users`, `tasks`, `calendar_events`.

Endpoints:
    GET  /api/v1/wall/summary           Today + upcoming + family + presence
    GET  /api/v1/wall/calendar          Month grid (year, month query params)
    GET  /api/v1/wall/week              7-day grid (start=YYYY-MM-DD)
    GET  /api/v1/wall/family            Roster
    GET  /api/v1/wall/events/stream     SSE bridge to family-bus (whitelisted topics)
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import structlog
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.config import settings as app_settings
from cara.models.shopping import ShoppingItem
from cara.models.task import Task
from cara.models.user import User
from cara.services import admin_settings as admin_svc
from cara.services import family_bus, wall as wall_svc
from cara.store import get_session

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/wall", tags=["wall"])


# ─── Access control ──────────────────────────────────────────────────

_TRUSTED_PROXIES = {
    "172.31.0.5",   # nginx-proxy
    "172.31.0.20",  # cara-frontend nginx
    "127.0.0.1",
}
_TRUSTED_CIDRS = [
    ipaddress.ip_network("192.168.1.0/24"),
    ipaddress.ip_network("10.8.0.0/24"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("172.31.0.0/16"),  # internal docker proxy-net
]


def _client_ip(request: Request) -> str | None:
    """Same algorithm as auth._client_ip — walk X-Forwarded-For only
    when the direct hop is a known CARA proxy."""
    direct = request.client.host if request.client else None
    if direct and direct in _TRUSTED_PROXIES:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            for cand in xff.split(","):
                cand = cand.strip()
                if cand:
                    return cand
    return direct


def _ip_is_lan(ip_str: str | None) -> bool:
    if not ip_str:
        return False
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(ip in net for net in _TRUSTED_CIDRS)


async def require_lan(request: Request) -> None:
    """Dependency: 403 unless the request is from a trusted CIDR."""
    ip = _client_ip(request)
    if not _ip_is_lan(ip):
        log.info("wall.rejected_non_lan", client_ip=ip, path=request.url.path)
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Wall surface is LAN-only",
        )


async def require_wall_enabled(
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    """Dependency: 503 if the admin disabled the Wall."""
    enabled = await admin_svc.get(session, "wall_enabled")
    if enabled is False:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Wall is disabled by admin",
        )


# ─── Endpoints ───────────────────────────────────────────────────────


@router.get("/summary")
async def summary(
    _lan: None = Depends(require_lan),  # noqa: B008
    _enabled: None = Depends(require_wall_enabled),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    return await wall_svc.build_today_summary(session)


@router.get("/calendar")
async def calendar(
    year: int = Query(..., ge=1900, le=2100),
    month: int = Query(..., ge=1, le=12),
    _lan: None = Depends(require_lan),  # noqa: B008
    _enabled: None = Depends(require_wall_enabled),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    return await wall_svc.build_calendar_grid(session, year=year, month=month)


@router.get("/week")
async def week(
    start: str = Query(..., description="ISO date of the Monday to start from"),
    _lan: None = Depends(require_lan),  # noqa: B008
    _enabled: None = Depends(require_wall_enabled),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    try:
        start_d = date.fromisoformat(start)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"invalid start date: {start}"
        ) from exc
    # Normalise to the Monday of that week (defensive — clients may pass any day).
    monday = start_d - timedelta(days=start_d.weekday())
    return await wall_svc.build_week(session, start=monday)


@router.get("/family")
async def family(
    _lan: None = Depends(require_lan),  # noqa: B008
    _enabled: None = Depends(require_wall_enabled),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[dict[str, Any]]:
    rows = await wall_svc.list_family(session)
    return [u.to_dict() for u in rows]


# ─── SSE bridge to family-bus ────────────────────────────────────────

_WALL_SAFE_TOPICS = (
    "presence.",      # presence.known.arrived, presence.unknown.detected
    "proactivity.",   # proactivity.fired:rule_id
    "tts.speaking.",  # tts.speaking.start, tts.speaking.end
    "task.due_soon",
    "system.",        # system.idle, system.online
)


def _topic_is_wall_safe(kind: str) -> bool:
    if not kind:
        return False
    return any(kind == t.rstrip(".") or kind.startswith(t) for t in _WALL_SAFE_TOPICS)


async def _wall_event_stream() -> AsyncGenerator[str, None]:
    """SSE generator: subscribes to the family bus and re-emits only
    Wall-safe events. Heartbeats every 25s so intermediate proxies
    don't close idle TCP connections."""
    yield "event: hello\ndata: {}\n\n"
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=256)

    async def _ingest() -> None:
        async for msg in family_bus.subscribe():
            kind = (msg.get("kind") or "").strip()
            if not _topic_is_wall_safe(kind):
                continue
            payload = msg.get("payload") or {}
            # Strip anything that smells private. We keep small known
            # fields; the rest is dropped.
            safe = {
                k: v for k, v in payload.items()
                if k in ("name", "rule_id", "title", "minutes_ago",
                         "count", "ts", "label")
            }
            ev = {"kind": kind, "payload": safe}
            try:
                queue.put_nowait(
                    f"event: {kind}\ndata: {json.dumps(ev, separators=(',', ':'))}\n\n"
                )
            except asyncio.QueueFull:
                # Drop on overflow — Wall reads cosmetic events, late
                # is worse than missed.
                pass

    task = asyncio.create_task(_ingest(), name="wall.sse_ingest")
    try:
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=25.0)
                yield msg
            except asyncio.TimeoutError:
                # SSE comment as heartbeat (clients ignore it).
                yield ": ping\n\n"
    except asyncio.CancelledError:
        raise
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


@router.get("/events/stream")
async def events_stream(
    _lan: None = Depends(require_lan),  # noqa: B008
    _enabled: None = Depends(require_wall_enabled),  # noqa: B008
) -> StreamingResponse:
    return StreamingResponse(
        _wall_event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Voice ask (LAN, no-auth) ────────────────────────────────────────


class WallAskBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    voice: bool = True


class WallAskOut(BaseModel):
    text: str
    audio_base64: str | None = None
    audio_mime: str | None = None
    sample_rate: int | None = None


async def _first_admin(session: AsyncSession) -> User | None:
    return (
        await session.execute(
            select(User)
            .where(User.is_admin.is_(True), User.is_active.is_(True))
            .order_by(User.id.asc())
            .limit(1)
        )
    ).scalar_one_or_none()


@router.post("/ask", response_model=WallAskOut)
async def wall_ask(
    body: WallAskBody,
    _lan: None = Depends(require_lan),  # noqa: B008
    _enabled: None = Depends(require_wall_enabled),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> WallAskOut:
    """Wall voice/text ask — runs the chat Pipeline as the first admin
    and returns text + (optionally) Piper audio inline.

    The Wall is shared/public, so we don't persist this exchange to a
    user's chat history. We tag the conversation as `wall-shared` so
    follow-ups in the same session can keep context."""
    admin = await _first_admin(session)
    if admin is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "no admin user")

    text = body.text.strip()
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty text")

    # Run the deterministic pipeline (intent_router → skills → recipe).
    # If every stage misses, fall through to the LLM.
    from cara.api.v1._chat_pipeline import execute_pipeline_collect  # noqa: PLC0415

    answer: str | None = None
    try:
        answer = await execute_pipeline_collect(
            session=session,
            user=admin,
            text=text,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("wall.ask.pipeline_failed", error=str(exc))
        answer = None

    if not answer:
        # Free-chat fallback through the LLM. We avoid streaming since
        # the Wall plays full audio at the end anyway.
        try:
            from cara.ai import get_llm_service  # noqa: PLC0415
            from cara.ai.llm import LLMUnavailableError  # noqa: PLC0415

            llm = get_llm_service()
            chunks: list[str] = []
            async for tok in llm.generate(
                f"Domanda: {text}\n\nRispondi in italiano, breve e diretta. "
                f"Sei CARA, l'AI domestica della famiglia.",
                max_new_tokens=200,
            ):
                chunks.append(tok.text)
            answer = "".join(chunks).strip() or "Non ho capito, puoi ripetere?"
        except LLMUnavailableError:
            answer = "Sto avendo un problema con il modello. Riprova."
        except Exception as exc:  # noqa: BLE001
            log.warning("wall.ask.llm_failed", error=str(exc))
            answer = "Mi spiace, non riesco a rispondere ora."

    audio_b64: str | None = None
    audio_mime: str | None = None
    sr: int | None = None
    if body.voice:
        try:
            from cara.ai.tts import get_tts_service  # noqa: PLC0415

            tts = get_tts_service()
            wav, sr = await tts.synthesize_wav(answer)
            if wav:
                audio_b64 = base64.b64encode(wav).decode("ascii")
                audio_mime = "audio/wav"
        except Exception as exc:  # noqa: BLE001
            log.warning("wall.ask.tts_failed", error=str(exc))

    return WallAskOut(
        text=answer,
        audio_base64=audio_b64,
        audio_mime=audio_mime,
        sample_rate=sr,
    )


# ─── Camera snapshots (LAN, no-auth) ─────────────────────────────────


async def _list_wall_cameras_raw(session: AsyncSession) -> list[dict[str, Any]]:
    """List cameras for the Wall rotation. Falls back to a direct
    Frigate `/api/config` + `/api/stats` lookup so we don't depend on
    the `last_recording_time` field — Frigate ≥0.14 nests stats under
    `stats["cameras"][cam_id]` with `camera_fps` instead, so the
    `cameras_svc.list_cameras` heuristic returns nothing.

    Online == `camera_fps > 0` for the live FPS path (works on 0.14).
    Hidden cameras (admin-set `presence_relevant: false`) are skipped.
    """
    from cara.config import settings  # noqa: PLC0415

    base = await admin_svc.get(session, "frigate_url")
    base = (base or settings.frigate_url or "").rstrip("/")
    if not base:
        return []
    overrides_raw = await admin_svc.get(session, "cameras")
    overrides = overrides_raw if isinstance(overrides_raw, dict) else {}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(4.0, connect=2.0)) as c:
            r_cfg = await c.get(f"{base}/api/config")
            r_cfg.raise_for_status()
            cfg = r_cfg.json()
            try:
                r_st = await c.get(f"{base}/api/stats")
                r_st.raise_for_status()
                stats = r_st.json()
            except httpx.HTTPError:
                stats = {}
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("wall.cameras.frigate_unreachable", error=str(exc))
        return []

    nested = stats.get("cameras") if isinstance(stats.get("cameras"), dict) else stats
    out: list[dict[str, Any]] = []
    for cam_id in (cfg.get("cameras") or {}).keys():
        ovr = overrides.get(cam_id) or {}
        if ovr.get("presence_relevant") is False:
            continue
        cam_stats = (nested or {}).get(cam_id) or {}
        fps = cam_stats.get("camera_fps") or 0
        online = bool(fps and float(fps) > 0)
        if not online:
            continue
        label = (
            ovr.get("label") if isinstance(ovr.get("label"), str) and ovr.get("label").strip()
            else cam_id.replace("_", " ").title()
        )
        out.append({
            "id": cam_id,
            "label": label,
            "area": ovr.get("area"),
            "online": True,
            "last_seen": None,  # 0.14 doesn't expose this; we trust fps>0
            "snapshot_url": f"/api/v1/wall/cameras/{cam_id}/snapshot.jpg",
        })
    out.sort(key=lambda x: x["label"])
    return out


@router.get("/cameras")
async def list_wall_cameras(
    _lan: None = Depends(require_lan),  # noqa: B008
    _enabled: None = Depends(require_wall_enabled),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[dict[str, Any]]:
    return await _list_wall_cameras_raw(session)


@router.get("/cameras/{cam_id}/snapshot.jpg")
async def camera_snapshot(
    cam_id: str,
    _lan: None = Depends(require_lan),  # noqa: B008
    _enabled: None = Depends(require_wall_enabled),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Response:
    """Same-origin proxy for the latest frame of `cam_id`. Filters
    cameras that aren't `presence_relevant` so a 'private' camera flag
    can hide it from the Wall even though Frigate still records."""
    # Allowlist via the live Wall camera list (same online + override
    # check as /cameras). Prevents path traversal and probes for
    # arbitrary Frigate endpoints.
    cams = await _list_wall_cameras_raw(session)
    cam = next((c for c in cams if c["id"] == cam_id), None)
    if cam is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "unknown or hidden camera"
        )

    from cara.config import settings  # noqa: PLC0415
    base = await admin_svc.get(session, "frigate_url")
    base = (base or settings.frigate_url or "").rstrip("/")
    if not base:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "frigate not configured")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0)) as c:
            r = await c.get(f"{base}/api/{cam_id}/latest.jpg")
            if r.status_code != 200:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    f"frigate replied {r.status_code}",
                )
            return Response(
                content=r.content,
                media_type=r.headers.get("content-type", "image/jpeg"),
                headers={
                    # Wall rotates every ~8s, so a tight client cache
                    # plus a query bust on the front-end gives us cheap
                    # but fresh frames.
                    "Cache-Control": "private, max-age=3",
                },
            )
    except httpx.HTTPError as exc:
        log.warning("wall.snapshot.failed", cam=cam_id, error=str(exc))
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "frigate unreachable"
        ) from exc


# ─── ASR (LAN, no-auth) ──────────────────────────────────────────────


_MAX_AUDIO_BYTES = 8 * 1024 * 1024  # 8 MB → ~60s WebM Opus 64kbps


@router.post("/asr")
async def wall_asr(
    audio: UploadFile = File(...),  # noqa: B008
    language: str = Form(default="it"),
    _lan: None = Depends(require_lan),  # noqa: B008
    _enabled: None = Depends(require_wall_enabled),  # noqa: B008
) -> dict[str, Any]:
    """Transcribe an uploaded audio blob via faster-whisper.

    Same engine as `/api/v1/asr/transcribe` but bypasses JWT — Wall is
    LAN-only kiosk surface. Used by `WallMic` when the browser does not
    expose `webkitSpeechRecognition` (Firefox, Safari without flags) or
    when offline (Web Speech requires Google's servers in Chrome).
    """
    if not app_settings.whisper_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Whisper disabled"
        )
    blob = await audio.read()
    if not blob:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty audio")
    if len(blob) > _MAX_AUDIO_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"audio too large (max {_MAX_AUDIO_BYTES} bytes)",
        )
    try:
        from cara.services import asr as asr_svc  # noqa: PLC0415

        return await asr_svc.transcribe_bytes(blob, language=language)
    except Exception as exc:  # noqa: BLE001
        log.warning("wall.asr.failed", error=str(exc))
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"transcription failed: {exc}",
        ) from exc


# ─── Tasks edit (LAN, no-auth) ───────────────────────────────────────


class WallTaskBody(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    due_date: str | None = None  # ISO; "" or null clears
    done: bool | None = None
    owner_id: int | None = None
    wall_visible: bool | None = None


def _ser_task(task: Task, owner: wall_svc.WallUser | None) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "title": task.title,
        "due_date": task.due_date.astimezone(UTC).isoformat() if task.due_date else None,
        "done": bool(task.done),
        "owner_id": task.user_id,
        "owner": owner.to_dict() if owner else None,
        "wall_visible": bool(task.wall_visible),
        "kind": "task",
    }


@router.get("/tasks/{task_id}")
async def wall_task_get(
    task_id: str,
    _lan: None = Depends(require_lan),  # noqa: B008
    _enabled: None = Depends(require_wall_enabled),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    try:
        tid = uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "invalid task id"
        ) from exc
    task = await session.get(Task, tid)
    if task is None or not task.wall_visible:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    owners = await wall_svc.visible_owner_index(session)
    return _ser_task(task, owners.get(task.user_id))


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
async def wall_task_create(
    body: WallTaskBody,
    _lan: None = Depends(require_lan),  # noqa: B008
    _enabled: None = Depends(require_wall_enabled),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    if not body.title or not body.title.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "title required")
    owners = await wall_svc.visible_owner_index(session)
    if body.owner_id and body.owner_id not in owners:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "owner is not a Wall-visible user"
        )
    if not body.owner_id:
        admin = await _first_admin(session)
        if admin is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "no admin user"
            )
        owner_id = admin.id
    else:
        owner_id = body.owner_id
    due = _parse_iso(body.due_date) if body.due_date else None
    task = Task(
        user_id=owner_id,
        title=body.title.strip(),
        done=bool(body.done),
        due_date=due,
        wall_visible=True if body.wall_visible is None else bool(body.wall_visible),
    )
    session.add(task)
    await session.flush()
    await family_bus.publish(
        "task.created", payload={"id": str(task.id), "title": task.title}
    )
    return _ser_task(task, owners.get(task.user_id))


@router.patch("/tasks/{task_id}")
async def wall_task_patch(
    task_id: str,
    body: WallTaskBody,
    _lan: None = Depends(require_lan),  # noqa: B008
    _enabled: None = Depends(require_wall_enabled),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    try:
        tid = uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "invalid task id"
        ) from exc
    task = await session.get(Task, tid)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    fields = body.model_fields_set
    if "title" in fields and body.title:
        task.title = body.title.strip()
    if "due_date" in fields:
        task.due_date = _parse_iso(body.due_date) if body.due_date else None
        task.reminded_at = None
    if "done" in fields and body.done is not None:
        task.done = body.done
        task.completed_at = datetime.now(UTC) if body.done else None
    if "owner_id" in fields and body.owner_id is not None:
        owners = await wall_svc.visible_owner_index(session)
        if body.owner_id not in owners:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "owner is not a Wall-visible user"
            )
        task.user_id = body.owner_id
    if "wall_visible" in fields and body.wall_visible is not None:
        task.wall_visible = body.wall_visible
    session.add(task)
    await session.flush()
    await family_bus.publish(
        "task.updated", payload={"id": str(task.id)}
    )
    owners = await wall_svc.visible_owner_index(session)
    return _ser_task(task, owners.get(task.user_id))


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def wall_task_delete(
    task_id: str,
    _lan: None = Depends(require_lan),  # noqa: B008
    _enabled: None = Depends(require_wall_enabled),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    try:
        tid = uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "invalid task id"
        ) from exc
    task = await session.get(Task, tid)
    if task is None:
        return None
    await session.delete(task)
    await session.flush()
    await family_bus.publish("task.deleted", payload={"id": task_id})
    return None


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"invalid datetime: {s}"
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


# ─── Shopping list (LAN, no-auth) ────────────────────────────────────


_SHOP_CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    ("Frutta e verdura", (
        "mela", "mele", "pera", "pere", "banana", "banane", "arancia", "arance",
        "limone", "limoni", "fragola", "fragole", "uva", "kiwi", "ananas",
        "pomodoro", "pomodori", "insalata", "lattuga", "rucola", "spinaci",
        "carota", "carote", "patata", "patate", "cipolla", "cipolle", "aglio",
        "zucchina", "zucchine", "melanzana", "melanzane", "peperone", "peperoni",
        "broccoli", "cavolo", "cavolfiore", "finocchio", "finocchi", "verdura",
        "frutta", "sedano", "prezzemolo", "basilico", "limoni",
    )),
    ("Latticini e uova", (
        "latte", "yogurt", "burro", "panna", "mozzarella", "ricotta", "parmigiano",
        "grana", "formaggio", "stracchino", "philadelphia", "scamorza", "uova", "uovo",
    )),
    ("Carne e pesce", (
        "carne", "pollo", "manzo", "vitello", "maiale", "tacchino", "salsiccia",
        "salsicce", "wurstel", "prosciutto", "bresaola", "salame", "pancetta",
        "tonno", "salmone", "pesce", "merluzzo", "branzino", "orata", "gamberi",
        "calamari", "polpo",
    )),
    ("Pane e cereali", (
        "pane", "pancarrè", "grissini", "crackers", "biscotti", "fette",
        "pasta", "spaghetti", "penne", "fusilli", "riso", "farro", "orzo",
        "cereali", "muesli", "fiocchi", "farina",
    )),
    ("Bevande", (
        "acqua", "vino", "birra", "succo", "succhi", "coca", "cola", "fanta",
        "sprite", "tè", "tea", "caffè", "caffe", "tisana", "limonata",
    )),
    ("Casa e igiene", (
        "detersivo", "ammorbidente", "candeggina", "sgrassatore", "sapone",
        "shampoo", "doccia", "dentifricio", "spazzolino", "deodorante",
        "carta", "asciugatutto", "tovaglioli", "fazzoletti", "pannolini",
        "lampadina", "lampadine", "scotch", "buste", "spugne", "guanti",
    )),
    ("Surgelati", (
        "surgelat", "gelato", "ghiaccioli",
    )),
    ("Dolci", (
        "cioccolato", "cioccolata", "biscotti", "torta", "cornetto", "merenda",
        "snack", "patatine", "caramelle", "marmellata", "miele", "zucchero",
        "nutella",
    )),
]


def _categorize(title: str) -> str:
    t = title.lower()
    for cat, words in _SHOP_CATEGORIES:
        for w in words:
            if w in t:
                return cat
    return "Altro"


def _ser_shop(item: ShoppingItem, owner: wall_svc.WallUser | None) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "title": item.title,
        "qty": item.qty,
        "bought": bool(item.bought),
        "owner_id": item.user_id,
        "owner": owner.to_dict() if owner else None,
        "category": _categorize(item.title),
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


class WallShopBody(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    qty: str | None = Field(None, max_length=40)
    bought: bool | None = None
    owner_id: int | None = None


@router.get("/shopping")
async def wall_shopping_list(
    _lan: None = Depends(require_lan),  # noqa: B008
    _enabled: None = Depends(require_wall_enabled),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """Family shopping list grouped by category (auto-classified). Items
    not bought first; bought ones in a separate bucket."""
    owners = await wall_svc.visible_owner_index(session)
    rows = (
        await session.execute(
            select(ShoppingItem)
            .where(ShoppingItem.user_id.in_(owners.keys()))
            .order_by(ShoppingItem.bought.asc(), ShoppingItem.created_at.asc())
        )
    ).scalars().all()

    todo_groups: dict[str, list[dict[str, Any]]] = {}
    bought: list[dict[str, Any]] = []
    for it in rows:
        ser = _ser_shop(it, owners.get(it.user_id))
        if ser["bought"]:
            bought.append(ser)
        else:
            todo_groups.setdefault(ser["category"], []).append(ser)

    # Stable category order: respect _SHOP_CATEGORIES order, then "Altro"
    ordered_keys = [c[0] for c in _SHOP_CATEGORIES] + ["Altro"]
    groups = [
        {"name": k, "items": todo_groups[k]}
        for k in ordered_keys if k in todo_groups
    ]
    return {
        "groups": groups,
        "bought": bought,
        "family": [u.to_dict() for u in owners.values()],
        "totals": {
            "todo": sum(len(g["items"]) for g in groups),
            "bought": len(bought),
        },
    }


@router.post("/shopping", status_code=status.HTTP_201_CREATED)
async def wall_shopping_create(
    body: WallShopBody,
    _lan: None = Depends(require_lan),  # noqa: B008
    _enabled: None = Depends(require_wall_enabled),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    if not body.title or not body.title.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "title required")
    owners = await wall_svc.visible_owner_index(session)
    if body.owner_id is not None and body.owner_id not in owners:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "owner not Wall-visible"
        )
    if body.owner_id is None:
        admin = await _first_admin(session)
        if admin is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "no admin user"
            )
        owner_id = admin.id
    else:
        owner_id = body.owner_id
    item = ShoppingItem(
        user_id=owner_id,
        title=body.title.strip(),
        qty=(body.qty or None),
        bought=bool(body.bought),
        bought_at=datetime.now(UTC) if body.bought else None,
    )
    session.add(item)
    await session.flush()
    await family_bus.publish(
        "shopping.created", payload={"id": str(item.id), "title": item.title}
    )
    return _ser_shop(item, owners.get(item.user_id))


@router.patch("/shopping/{item_id}")
async def wall_shopping_patch(
    item_id: str,
    body: WallShopBody,
    _lan: None = Depends(require_lan),  # noqa: B008
    _enabled: None = Depends(require_wall_enabled),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    try:
        sid = uuid.UUID(item_id)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "invalid item id"
        ) from exc
    item = await session.get(ShoppingItem, sid)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")
    fields = body.model_fields_set
    if "title" in fields and body.title:
        item.title = body.title.strip()
    if "qty" in fields:
        item.qty = body.qty or None
    if "bought" in fields and body.bought is not None:
        item.bought = body.bought
        item.bought_at = datetime.now(UTC) if body.bought else None
    if "owner_id" in fields and body.owner_id is not None:
        owners = await wall_svc.visible_owner_index(session)
        if body.owner_id not in owners:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "owner not Wall-visible"
            )
        item.user_id = body.owner_id
    session.add(item)
    await session.flush()
    await family_bus.publish(
        "shopping.updated", payload={"id": str(item.id)}
    )
    owners = await wall_svc.visible_owner_index(session)
    return _ser_shop(item, owners.get(item.user_id))


@router.delete("/shopping/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def wall_shopping_delete(
    item_id: str,
    _lan: None = Depends(require_lan),  # noqa: B008
    _enabled: None = Depends(require_wall_enabled),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    try:
        sid = uuid.UUID(item_id)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "invalid item id"
        ) from exc
    item = await session.get(ShoppingItem, sid)
    if item is None:
        return None
    await session.delete(item)
    await session.flush()
    await family_bus.publish("shopping.deleted", payload={"id": item_id})
    return None


# ─── Face check from device camera (LAN, no-auth) ───────────────────


_FACE_DEVICE_COOLDOWN_SEC = 90  # don't re-greet the same person more than every 90s


@router.post("/face-check")
async def wall_face_check(
    image: UploadFile = File(...),  # noqa: B008
    _lan: None = Depends(require_lan),  # noqa: B008
    _enabled: None = Depends(require_wall_enabled),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """Recognize faces from the device camera.

    The Wall frontend captures a frame from `getUserMedia` every ~30s
    and POSTs it here. We forward to frigate-faces' `/api/recognize-image`
    and (on a known match) publish a `presence.known.arrived` event on
    the family bus so the avatar greets and the rest of the family-bus
    consumers behave exactly like a Frigate camera sighting.

    Cooldown via Redis keeps repeated arrivals from spamming the bus.
    """
    blob = await image.read()
    if not blob:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty image")
    if len(blob) > 4 * 1024 * 1024:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "image too large (max 4 MB)",
        )

    base = await admin_svc.get(session, "frigate_faces_url")
    base = (base or app_settings.frigate_faces_url or "").rstrip("/")
    if not base:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "frigate-faces not configured",
        )

    try:
        # 25 s total: face_recognition's HOG detector + encoding can
        # take a few seconds on a busy box, plus the upload itself
        # (~1-2 MB Antonio test images are slow on the proxy hop).
        # 320×240 device-cam frames complete in well under 1 s.
        async with httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=3.0)) as c:
            r = await c.post(
                f"{base}/api/recognize-image",
                files={"image": (image.filename or "frame.jpg", blob, image.content_type or "image/jpeg")},
            )
    except httpx.HTTPError as exc:
        # Connection / timeout / DNS — upstream genuinely unreachable.
        log.warning("wall.face_check.upstream_unreachable", error=str(exc) or type(exc).__name__)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "frigate-faces unreachable") from exc

    if r.status_code >= 500:
        log.warning("wall.face_check.upstream_5xx", status=r.status_code, body=r.text[:200])
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "frigate-faces server error")
    if r.status_code >= 400:
        # Bad image, unsupported format, etc. — propagate upstream's complaint
        # so the kiosk can show something useful instead of a misleading 502.
        upstream_msg = ""
        try:
            upstream_msg = (r.json() or {}).get("error") or ""
        except Exception:  # noqa: BLE001
            upstream_msg = r.text[:200]
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"frigate-faces rejected image: {upstream_msg or r.status_code}",
        )
    try:
        data = r.json()
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "frigate-faces returned non-JSON"
        ) from exc

    match = data.get("match") if isinstance(data, dict) else None
    found_face = bool(data.get("found_face")) if isinstance(data, dict) else False

    # Publish a presence event when we have a known person, with a
    # Redis-backed cooldown to avoid greeting the same person every
    # 30s. The Wall avatar consumer dedupes by `name`.
    if match and isinstance(match, dict) and match.get("name"):
        name = str(match["name"])
        try:
            from cara.config import settings as _cfg  # noqa: PLC0415
            import redis.asyncio as redis_asyncio  # noqa: PLC0415

            r = redis_asyncio.from_url(_cfg.redis_url, decode_responses=True)
            key = f"wall:device_face:{name.lower()}"
            already = await r.get(key)
            if not already:
                await r.set(key, "1", ex=_FACE_DEVICE_COOLDOWN_SEC)
                await family_bus.publish(
                    "presence.known.arrived",
                    payload={"name": name, "source": "wall_device_cam"},
                )
            await r.aclose()
        except Exception as exc:  # noqa: BLE001
            log.warning("wall.face_check.bus_failed", error=str(exc))

    return {
        "found_face": found_face,
        "match": match,
        "cooldown_sec": _FACE_DEVICE_COOLDOWN_SEC,
    }


@router.post("/shopping/clear-bought", status_code=status.HTTP_204_NO_CONTENT)
async def wall_shopping_clear_bought(
    _lan: None = Depends(require_lan),  # noqa: B008
    _enabled: None = Depends(require_wall_enabled),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    from sqlalchemy import delete  # noqa: PLC0415

    await session.execute(delete(ShoppingItem).where(ShoppingItem.bought.is_(True)))
    await session.flush()
    await family_bus.publish("shopping.cleared", payload={})
    return None

