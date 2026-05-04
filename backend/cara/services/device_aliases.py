"""Device aliases service — CRUD + merge with NLU's auto-derived list.

The NLU resolver in `cara.smarthome.nlu` accepts a list of
`DeviceAlias` (the dataclass, not the ORM row) at construction. The
auto layer comes from `aliases_from_entities(entities)`. The admin
layer comes from this service via `merged_aliases(...)`.

Both layers are deduplicated on (entity_id, lowercase alias). The
admin layer wins when a phrase is mapped to two different entities
(unlikely — the unique constraint already prevents that for a single
admin-curated mapping).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models.device_alias import DeviceAlias as DeviceAliasORM
from cara.smarthome import Entity
from cara.smarthome.nlu import (
    DeviceAlias as NLUAlias,
    aliases_from_entities,
)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def create_alias(
    session: AsyncSession,
    *,
    entity_id: str,
    alias: str,
    area: str | None = None,
    source_user_id: int | None = None,
    commit: bool = False,
) -> DeviceAliasORM:
    if not entity_id.strip() or ":" not in entity_id:
        raise ValueError("entity_id must be canonical (provider:local_id)")
    if not alias.strip() or len(alias) > 120:
        raise ValueError("alias must be 1..120 chars")
    row = DeviceAliasORM(
        entity_id=entity_id.strip(),
        alias=alias.strip(),
        area=(area.strip() if area else None),
        source_user_id=source_user_id,
    )
    session.add(row)
    await session.flush()
    if commit:
        await session.commit()
    return row


async def list_aliases(
    session: AsyncSession, *, entity_id: str | None = None,
    limit: int = 500,
) -> list[DeviceAliasORM]:
    stmt = select(DeviceAliasORM).order_by(
        DeviceAliasORM.entity_id, DeviceAliasORM.alias,
    )
    if entity_id is not None:
        stmt = stmt.where(DeviceAliasORM.entity_id == entity_id)
    return list((await session.execute(stmt.limit(limit))).scalars().all())


async def delete_alias(
    session: AsyncSession, alias_id: int, *, commit: bool = False,
) -> bool:
    row = (await session.execute(
        select(DeviceAliasORM).where(DeviceAliasORM.id == alias_id)
    )).scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    if commit:
        await session.commit()
    return True


# ---------------------------------------------------------------------------
# Merge with NLU auto-derived list
# ---------------------------------------------------------------------------


async def merged_aliases(
    session: AsyncSession,
    *,
    entities: list[Entity],
) -> list[NLUAlias]:
    """Compose the alias list the NLU resolver consumes.

    Order:
      1. Admin-curated rows from `device_aliases` (source="user")
      2. Auto-derived from `friendly_name` + local-id fallback
         (source="auto"), skipping any (entity, alias-norm) pair the
         admin layer already covers.

    The NLU exact-match comparison is accent + case insensitive, so we
    dedupe on the same normalised form to avoid feeding the resolver
    duplicates.
    """
    auto = aliases_from_entities(entities)
    # Admin overrides — most recent first so newer corrections win.
    rows = list((await session.execute(
        select(DeviceAliasORM).order_by(DeviceAliasORM.updated_at.desc())
    )).scalars().all())

    seen: set[tuple[str, str]] = set()
    out: list[NLUAlias] = []

    for row in rows:
        key = (row.entity_id, row.alias.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(NLUAlias(
            entity_id=row.entity_id,
            alias=row.alias,
            area=row.area,
            source="user",
        ))

    for a in auto:
        key = (a.entity_id, a.alias.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(a)

    return out


# ---------------------------------------------------------------------------
# Test diagnostic — admin "voice mapping test"
# ---------------------------------------------------------------------------


@dataclass
class AliasResolutionPreview:
    utterance: str
    matched_entity_id: str | None
    matched_alias: str | None
    score: float
    source: str
    candidates_count: int


async def preview_resolution(
    session: AsyncSession,
    *,
    utterance: str,
    entities: list[Entity],
    embedder=None,
    present_in_area: str | None = None,
) -> AliasResolutionPreview:
    """Run the NLU resolver against the merged alias list. Useful for
    the admin "voice mapping test" UI: type a phrase, see what CARA
    would resolve it to."""
    from cara.smarthome.nlu import SmartHomeNLU

    aliases = await merged_aliases(session, entities=entities)
    nlu = SmartHomeNLU(aliases, embedder=embedder)
    res = await nlu.resolve(utterance, present_in_area=present_in_area)
    chosen = res.chosen
    return AliasResolutionPreview(
        utterance=utterance,
        matched_entity_id=chosen.entity_id if chosen else None,
        matched_alias=chosen.alias if chosen else None,
        score=chosen.score if chosen else 0.0,
        source=chosen.source if chosen else res.reason,
        candidates_count=len(res.candidates),
    )
