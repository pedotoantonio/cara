"""Smart-home permission check — does THIS user have rights for THIS action?

Resolution order (highest priority first):

  1. Per-user explicit DENY  (user-level lock-out always wins)
  2. Per-user explicit ALLOW or ASK
  3. Role default (DEFAULT_ROLE_MATRIX, in code)

Pattern matching is fnmatch-style globs over canonical entity ids
(`ha:light.*`, `ha:lock.front_door`, `*:alarm_control_panel.*`).
Specificity wins on ties: a pattern with more non-wildcard characters
beats a broader one. If two equal-specificity patterns conflict, the
more recent `updated_at` wins.

Service is intentionally pure-data: it works on `Entity` ids and a
user role string, no HA / MQTT side effects. The chat layer composes
this with the adapter to turn "deny" into "non posso, l'admin l'ha
bloccato".
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models.device_permission import (
    ACTION_ALARM,
    ACTION_CONTROL,
    ACTION_LOCK,
    ACTION_QUERY,
    PERM_ALLOW,
    PERM_ASK,
    PERM_DENY,
    DevicePermission,
)


Decision = Literal["allow", "deny", "ask"]


# ---------------------------------------------------------------------------
# Default role matrix — applies when no explicit row matches.
# ---------------------------------------------------------------------------
#
# Conservative on purpose. Family roles map roughly to:
#   parent  → trusted adult: full read + write everywhere by default
#   teen    → most things, no locks/alarm
#   child   → read everywhere, only own-room write (we leave own-room
#             scoping to per-user explicit ALLOW rows)
#   elder   → read + write lights/climate/cover, no locks/alarm
#   guest   → read-only, no control
#
# Each role gets a list of (pattern, action, decision). First match
# inside a role wins, so write more specific patterns first.

_PARENT = (
    ("*:alarm_control_panel.*", ACTION_ALARM, PERM_ASK),  # confirm even for parents
    ("*:lock.*", ACTION_LOCK, PERM_ASK),                  # confirm locks too
    ("*", ACTION_CONTROL, PERM_ALLOW),
    ("*", ACTION_QUERY, PERM_ALLOW),
    ("*", ACTION_LOCK, PERM_ALLOW),
    ("*", ACTION_ALARM, PERM_ALLOW),
)

_TEEN = (
    ("*:alarm_control_panel.*", ACTION_ALARM, PERM_DENY),
    ("*:lock.*", ACTION_LOCK, PERM_DENY),
    ("*:lock.*", ACTION_CONTROL, PERM_DENY),
    ("*", ACTION_CONTROL, PERM_ALLOW),
    ("*", ACTION_QUERY, PERM_ALLOW),
)

_CHILD = (
    ("*:alarm_control_panel.*", "*", PERM_DENY),
    ("*:lock.*", "*", PERM_DENY),
    ("*:climate.*", ACTION_CONTROL, PERM_DENY),     # no thermostat
    ("*", ACTION_QUERY, PERM_ALLOW),
    # Control left to per-user explicit ALLOW rows for own-room devices.
)

_ELDER = (
    ("*:alarm_control_panel.*", "*", PERM_DENY),
    ("*:lock.*", "*", PERM_DENY),
    ("*:light.*", ACTION_CONTROL, PERM_ALLOW),
    ("*:switch.*", ACTION_CONTROL, PERM_ALLOW),
    ("*:climate.*", ACTION_CONTROL, PERM_ALLOW),
    ("*:cover.*", ACTION_CONTROL, PERM_ALLOW),
    ("*", ACTION_QUERY, PERM_ALLOW),
)

_GUEST = (
    ("*", ACTION_QUERY, PERM_ALLOW),
    # Everything else falls through to the implicit deny.
)


DEFAULT_ROLE_MATRIX: dict[str, tuple[tuple[str, str, str], ...]] = {
    "parent": _PARENT,
    "teen": _TEEN,
    "child": _CHILD,
    "elder": _ELDER,
    "guest": _GUEST,
}


# ---------------------------------------------------------------------------
# Pattern specificity helper
# ---------------------------------------------------------------------------


def _pattern_specificity(pattern: str) -> int:
    """Higher = more specific. Counts non-wildcard chars."""
    return sum(1 for c in pattern if c not in "*?[]")


def _action_matches(rule_action: str, requested_action: str) -> bool:
    """Rule action `*` matches anything. Otherwise exact match."""
    return rule_action == "*" or rule_action == requested_action


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class PermissionCheck:
    decision: Decision
    matched_pattern: str | None = None
    matched_source: str = "default"   # "user" | "role" | "default"
    reason: str | None = None


async def check_permission(
    session: AsyncSession,
    *,
    user_id: int,
    user_role: str,
    entity_id: str,
    action: str = ACTION_CONTROL,
) -> PermissionCheck:
    """The single function the chat layer calls before invoking call_service.

    Implicit-deny on no match — safer than implicit-allow.
    """
    # 1. Per-user rules.
    user_rules = await _load_user_rules(session, user_id=user_id)
    user_decision = _evaluate_rules(
        rules=user_rules,
        entity_id=entity_id,
        action=action,
    )
    if user_decision is not None:
        pattern, decision, reason = user_decision
        return PermissionCheck(
            decision=decision, matched_pattern=pattern,
            matched_source="user", reason=reason,
        )

    # 2. Role default.
    role_table = DEFAULT_ROLE_MATRIX.get(user_role, _GUEST)
    role_decision = _evaluate_rules(
        rules=role_table,
        entity_id=entity_id,
        action=action,
    )
    if role_decision is not None:
        pattern, decision, _ = role_decision
        return PermissionCheck(
            decision=decision, matched_pattern=pattern, matched_source="role",
        )

    # 3. Implicit deny.
    return PermissionCheck(decision=PERM_DENY, matched_source="default",
                           reason="no rule matched, default deny")


async def _load_user_rules(
    session: AsyncSession, *, user_id: int,
) -> list[tuple[str, str, str, str | None]]:
    """All explicit DevicePermission rows for `user_id`, sorted by
    specificity desc + updated_at desc so first hit in evaluation wins."""
    stmt = (
        select(DevicePermission)
        .where(DevicePermission.user_id == user_id)
        .order_by(DevicePermission.updated_at.desc())
    )
    rows = list((await session.execute(stmt)).scalars().all())

    rules: list[tuple[str, str, str, str | None]] = [
        (r.entity_pattern, r.action, r.decision, r.reason) for r in rows
    ]
    rules.sort(key=lambda r: _pattern_specificity(r[0]), reverse=True)
    return rules  # type: ignore[return-value]


def _evaluate_rules(
    *,
    rules: Iterable[tuple],
    entity_id: str,
    action: str,
) -> tuple[str, Decision, str | None] | None:
    """Walk `rules`, return the first match as (pattern, decision, reason).

    Special priority: an explicit DENY anywhere in the list wins even
    over earlier ALLOW rules with longer-matching patterns. This mirrors
    "user opt-out always wins".
    """
    deny_match: tuple[str, Decision, str | None] | None = None
    first_match: tuple[str, Decision, str | None] | None = None

    for entry in rules:
        if len(entry) == 4:
            pattern, rule_action, decision, reason = entry
        else:
            pattern, rule_action, decision = entry  # type: ignore[misc]
            reason = None
        if not _action_matches(rule_action, action):
            continue
        if not fnmatch.fnmatchcase(entity_id, pattern):
            continue
        if first_match is None:
            first_match = (pattern, decision, reason)
        if decision == PERM_DENY and deny_match is None:
            deny_match = (pattern, decision, reason)

    return deny_match or first_match
