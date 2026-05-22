"""Agent State Machine γ — sorgente di verità unica per stato/mood/emotion.

Risolve il problema oggi: stato dell'avatar (CaraFace) calcolato in
4 posti diversi (WallMic FSM, HomePage FSM, useWallEventStream merge,
inferEmotion da testo). Cross-surface incoerenza garantita.

Soluzione γ: una sola FSM per `user_id`, esposta sul family-bus topic
`agent.state` come payload compatto. Tutti i clients (Wall, mobile
PWA v2, Telegram bot, future surface) leggono SOLO da qui.

Stati discreti:
- AgentEnergy: idle | listening | thinking | speaking | sensing | sleeping
- AgentEmotion: neutral | happy | thoughtful | confused | sad | surprised | ironic | tender
- AgentPosture: attentive | peeking | resting

Ogni transizione produce un nuovo `AgentSnapshot` con `expires_at`
opzionale (decay automatico a stato default dopo N secondi).

Sorgenti di transizione (chi chiama `transition`):
- chat.py → `thinking` on user message, `speaking` on TTS start, `idle` on done
- presence_events → `sensing` su unknown arrival
- proactivity rules → `peeking` quando vuole suggerire
- voice flow → `listening` su mic start

Lo stato vecchio (sparso) resta funzionante in legacy. La migrazione
clients procede uno alla volta: WallMic → useAgentState() in M1,
HomePage in M2, ecc.

API:
    snapshot = state.snapshot(user_id)
    state.transition(user_id, energy='thinking', emotion='thoughtful',
                     decay_seconds=8)

Storage: in-memory dict + Redis pub/sub. Su backend restart lo stato
viene reset a default (è cosmetico, non critico — niente persistence DB).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

import structlog
from redis.asyncio import Redis

from cara.config import settings


log = structlog.get_logger(__name__)


AgentEnergy = Literal[
    "idle",
    "listening",
    "thinking",
    "speaking",
    "sensing",
    "sleeping",
]
AgentEmotion = Literal[
    "neutral",
    "happy",
    "thoughtful",
    "confused",
    "sad",
    "surprised",
    "ironic",
    "tender",
]
AgentPosture = Literal["attentive", "peeking", "resting"]


@dataclass(slots=True)
class AgentSnapshot:
    """Stato istantaneo dell'avatar per un utente."""

    user_id: int
    energy: AgentEnergy = "idle"
    emotion: AgentEmotion = "neutral"
    posture: AgentPosture = "attentive"
    caption: str | None = None
    """Testo opzionale (es. "Sto pensando…", "X è arrivato")."""
    speaking_text_partial: str | None = None
    """Se l'agent sta dicendo qualcosa, il testo accumulato finora."""
    glow_accent: str = "coral"
    """Token colore per il glow halo. Mapped lato client."""
    pending_notifications: int = 0
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str | None = None
    """Se non-null, dopo questo timestamp l'avatar torna a default."""

    def to_topic_payload(self) -> dict[str, object]:
        return asdict(self)


DEFAULT_SNAPSHOT = AgentSnapshot(
    user_id=0,
    energy="idle",
    emotion="neutral",
    posture="attentive",
    glow_accent="coral",
)


# ── In-memory store per-user + Redis pub/sub ─────────────────────────


_store: dict[int, AgentSnapshot] = {}
_lock = asyncio.Lock()
_redis_pubsub_channel = "cara:agent.state"


async def _publish(snapshot: AgentSnapshot) -> None:
    """Pubblica lo snapshot sul Redis topic così WebSocket bridge e
    clients esterni (Telegram bot, futuro) ricevono il nuovo stato."""
    try:
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            await redis.publish(
                _redis_pubsub_channel,
                json.dumps(snapshot.to_topic_payload()),
            )
        finally:
            await redis.aclose()
    except Exception as exc:  # noqa: BLE001 — best-effort
        log.warning("agent_state.publish_failed", error=str(exc))


def snapshot(user_id: int) -> AgentSnapshot:
    """Ritorna lo snapshot corrente per user_id. Se non esiste o è
    expired, ritorna il default."""
    s = _store.get(user_id)
    if s is None:
        return AgentSnapshot(user_id=user_id)
    if s.expires_at:
        try:
            exp = datetime.fromisoformat(s.expires_at)
            if exp <= datetime.now(timezone.utc):
                # Decayed → ritorna default ma non rimuove da store
                # (il prossimo transition() sovrascrive comunque).
                return AgentSnapshot(user_id=user_id)
        except ValueError:
            pass
    return s


async def transition(
    user_id: int,
    *,
    energy: AgentEnergy | None = None,
    emotion: AgentEmotion | None = None,
    posture: AgentPosture | None = None,
    caption: str | None = None,
    speaking_text_partial: str | None = None,
    glow_accent: str | None = None,
    pending_notifications: int | None = None,
    decay_seconds: float | None = None,
) -> AgentSnapshot:
    """Crea / aggiorna lo snapshot per user_id e pubblica.

    Solo i campi non-None vengono aggiornati (merge), così callsite
    parziali (es. solo `energy='speaking'`) non azzerano gli altri.
    """
    async with _lock:
        current = _store.get(user_id) or AgentSnapshot(user_id=user_id)
        merged = AgentSnapshot(
            user_id=user_id,
            energy=energy if energy is not None else current.energy,
            emotion=emotion if emotion is not None else current.emotion,
            posture=posture if posture is not None else current.posture,
            caption=caption if caption is not None else current.caption,
            speaking_text_partial=(
                speaking_text_partial
                if speaking_text_partial is not None
                else current.speaking_text_partial
            ),
            glow_accent=(
                glow_accent if glow_accent is not None else current.glow_accent
            ),
            pending_notifications=(
                pending_notifications
                if pending_notifications is not None
                else current.pending_notifications
            ),
            started_at=datetime.now(timezone.utc).isoformat(),
            expires_at=(
                (datetime.now(timezone.utc) + timedelta(seconds=decay_seconds)).isoformat()
                if decay_seconds is not None
                else None
            ),
        )
        _store[user_id] = merged

    await _publish(merged)
    return merged


def all_snapshots() -> dict[int, AgentSnapshot]:
    """Per admin diagnostics: vedi lo stato di tutti gli user."""
    return dict(_store)


async def reset(user_id: int) -> AgentSnapshot:
    """Reset esplicito dello stato (es. logout)."""
    return await transition(
        user_id,
        energy="idle",
        emotion="neutral",
        posture="attentive",
        caption=None,
        speaking_text_partial=None,
        glow_accent="coral",
        pending_notifications=0,
    )
