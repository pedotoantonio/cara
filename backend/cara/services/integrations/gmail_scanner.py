"""Gmail scanner — periodically inspects the user's inbox, runs the
3-layer NLU, and writes pending proposals to `email_proposals`.

Privacy + read-only guarantees:
  - **Cara NON marca MAI le email come lette.** Usiamo `messages.list`
    e `messages.get` (GET-only); il label UNREAD non viene toccato.
    Lo scope OAuth `gmail.readonly` non permette comunque la modifica.
    Vedi `cara/integrations/google_gmail.py` per la guarantee completa.
  - Solo messaggi `newer_than:1d` (ultime 24h), niente promo/social
  - Body consumato in-memory, NON persistito: solo snippet 200 char
  - Idempotente su `message_id` (UNIQUE constraint)
  - Cap: max 20 messaggi analizzati per tick
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from cara.config import settings
from cara.integrations import google_gmail as gmail
from cara.integrations import google_oauth
from cara.models.email_proposal import EmailLearningSignal, EmailProposal
from cara.models.oauth_credentials import OAuthCredentials
from cara.services.integrations import email_understanding as nlu


log = structlog.get_logger(__name__)


_QUERY = "newer_than:1d -in:sent -category:promotions -category:social"


async def _get_blacklisted_senders(session, user_id: int) -> set[str]:
    """Senders the user has rejected ≥3 times — auto-skip."""
    rows = (
        await session.execute(
            select(EmailLearningSignal)
            .where(EmailLearningSignal.user_id == user_id)
            .where(EmailLearningSignal.signal_type == "from")
            .where(EmailLearningSignal.rejects >= 3)
        )
    ).scalars().all()
    return {r.pattern for r in rows}


async def _scan_one_user(
    sessionmaker: async_sessionmaker, cred_id: int,
) -> int:
    async with sessionmaker() as session:
        cred = await session.get(OAuthCredentials, cred_id)
        if cred is None or cred.revoked:
            return 0
        if cred.scope_set != "gmail:ro":
            return 0
        user_id = cred.user_id
        cfg = cred.config_json or {}
        cloud_fallback = bool(cfg.get("cloud_fallback_enabled"))
        blacklist = await _get_blacklisted_senders(session, user_id)

        try:
            token = await google_oauth.get_access_token(session, cred)
        except Exception as exc:  # noqa: BLE001
            log.warning("gmail_scan.token_failed", cred_id=cred_id, error=str(exc))
            return 0

    # List recent messages OUTSIDE the DB session.
    try:
        ids = await gmail.list_messages(token, query=_QUERY, max_results=30)
    except Exception as exc:  # noqa: BLE001
        log.warning("gmail_scan.list_failed", cred_id=cred_id, error=str(exc))
        return 0

    if not ids:
        return 0

    # Skip messages we already saw.
    async with sessionmaker() as session:
        existing = (
            await session.execute(
                select(EmailProposal.message_id)
                .where(EmailProposal.user_id == user_id)
                .where(EmailProposal.message_id.in_(ids))
            )
        ).scalars().all()
    seen = set(existing)
    todo = [m for m in ids if m not in seen]
    if not todo:
        return 0

    written = 0
    for mid in todo[:20]:   # safety cap per tick
        try:
            msg = await gmail.get_message(token, message_id=mid, format="full")
        except Exception as exc:  # noqa: BLE001
            log.info("gmail_scan.fetch_skip", id=mid, error=str(exc))
            continue

        sender = gmail.from_address(msg)
        if sender in blacklist:
            continue
        headers = gmail.parse_headers(msg)
        subject = headers.get("subject", "")
        body = gmail.extract_text(msg.get("payload"))

        # Run pipeline
        proposal = await nlu.classify_email(
            subject=subject, body=body, cloud_fallback=cloud_fallback,
        )
        if not proposal.is_relevant():
            # Track the negative as well so future runs short-circuit faster.
            continue

        snippet = re.sub(r"\s+", " ", (body or "")).strip()[:200]

        async with sessionmaker() as session:
            row = EmailProposal(
                user_id=user_id,
                message_id=mid,
                from_address=sender or None,
                subject=subject or None,
                snippet=snippet or None,
                proposal_type=proposal.proposal_type,
                proposal_args=nlu.proposal_to_args(proposal),
                confidence=proposal.confidence,
                source_layer=proposal.source_layer,
            )
            session.add(row)
            try:
                await session.commit()
                written += 1
            except Exception as exc:  # noqa: BLE001
                # Likely UNIQUE collision — another tick already wrote it.
                log.info("gmail_scan.dup", id=mid, error=str(exc))
                await session.rollback()

    if written:
        log.info("gmail_scan.proposals_written", cred_id=cred_id, n=written)
        # Refresh push channel so the UI reacts.
        try:
            from cara.services.family_bus import publish
            await publish("email.proposal.created", user_id=user_id, payload={"n": written})
        except Exception:  # noqa: BLE001
            pass
    return written


async def _scan_once(sessionmaker: async_sessionmaker) -> int:
    async with sessionmaker() as session:
        rows = (
            await session.execute(
                select(OAuthCredentials.id)
                .where(OAuthCredentials.provider == "google")
                .where(OAuthCredentials.scope_set == "gmail:ro")
                .where(OAuthCredentials.revoked.is_(False))
            )
        ).all()
        cred_ids = [r[0] for r in rows]

    total = 0
    for cid in cred_ids:
        try:
            total += await _scan_one_user(sessionmaker, cid)
        except Exception as exc:  # noqa: BLE001
            log.warning("gmail_scan.user_failed", cred_id=cid, error=str(exc))
    return total


async def run_loop(sessionmaker: async_sessionmaker) -> None:
    if not google_oauth.is_available():
        log.info("gmail_scan.skipped_unconfigured")
        return
    interval = max(120, settings.gmail_scan_interval_seconds)
    log.info("gmail_scan.start", interval_seconds=interval)
    try:
        while True:
            try:
                n = await _scan_once(sessionmaker)
                if n:
                    log.info("gmail_scan.tick", proposals=n)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("gmail_scan.tick_error", error=str(exc))
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        log.info("gmail_scan.stop")
        raise
