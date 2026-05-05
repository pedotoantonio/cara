"""Unit tests for `cara.services.smarthome_permissions`."""

from __future__ import annotations

import pytest

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
from cara.services.smarthome_permissions import (
    _pattern_specificity,
    check_permission,
)


pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------- specificity


def test_pattern_specificity_more_specific_higher() -> None:
    assert _pattern_specificity("ha:light.cucina") > _pattern_specificity("ha:light.*")
    assert _pattern_specificity("ha:light.*") > _pattern_specificity("*")


# --------------------------------------------------------------- helpers


async def _seed_user(db_session, uid: int, role: str = "parent"):
    from cara.models.user import User

    u = User(id=uid, email=f"u{uid}@example.com", password_hash="x",
             full_name=None, is_admin=False, is_active=True, role=role)
    db_session.add(u)
    await db_session.flush()
    return u


# --------------------------------------------------------------- role defaults


async def test_parent_default_can_query_lights(db_session) -> None:
    await _seed_user(db_session, 1, role="parent")
    out = await check_permission(
        db_session, user_id=1, user_role="parent",
        entity_id="ha:light.cucina", action=ACTION_QUERY,
    )
    assert out.decision == PERM_ALLOW
    assert out.matched_source == "role"


async def test_parent_default_can_control_lights(db_session) -> None:
    await _seed_user(db_session, 1)
    out = await check_permission(
        db_session, user_id=1, user_role="parent",
        entity_id="ha:light.cucina", action=ACTION_CONTROL,
    )
    assert out.decision == PERM_ALLOW


async def test_parent_locks_require_confirmation(db_session) -> None:
    await _seed_user(db_session, 1)
    out = await check_permission(
        db_session, user_id=1, user_role="parent",
        entity_id="ha:lock.front_door", action=ACTION_LOCK,
    )
    assert out.decision == PERM_ASK


async def test_parent_alarm_requires_confirmation(db_session) -> None:
    await _seed_user(db_session, 1)
    out = await check_permission(
        db_session, user_id=1, user_role="parent",
        entity_id="ha:alarm_control_panel.casa", action=ACTION_ALARM,
    )
    assert out.decision == PERM_ASK


async def test_teen_cannot_lock_or_unlock(db_session) -> None:
    await _seed_user(db_session, 2, role="teen")
    out = await check_permission(
        db_session, user_id=2, user_role="teen",
        entity_id="ha:lock.front_door", action=ACTION_LOCK,
    )
    assert out.decision == PERM_DENY


async def test_teen_cannot_arm_alarm(db_session) -> None:
    await _seed_user(db_session, 2, role="teen")
    out = await check_permission(
        db_session, user_id=2, user_role="teen",
        entity_id="ha:alarm_control_panel.casa", action=ACTION_ALARM,
    )
    assert out.decision == PERM_DENY


async def test_teen_can_control_lights(db_session) -> None:
    await _seed_user(db_session, 2, role="teen")
    out = await check_permission(
        db_session, user_id=2, user_role="teen",
        entity_id="ha:light.cucina", action=ACTION_CONTROL,
    )
    assert out.decision == PERM_ALLOW


async def test_child_cannot_control_climate(db_session) -> None:
    await _seed_user(db_session, 3, role="child")
    out = await check_permission(
        db_session, user_id=3, user_role="child",
        entity_id="ha:climate.salotto", action=ACTION_CONTROL,
    )
    assert out.decision == PERM_DENY


async def test_child_can_query(db_session) -> None:
    await _seed_user(db_session, 3, role="child")
    out = await check_permission(
        db_session, user_id=3, user_role="child",
        entity_id="ha:light.cucina", action=ACTION_QUERY,
    )
    assert out.decision == PERM_ALLOW


async def test_child_default_no_control_unless_explicit_allow(db_session) -> None:
    await _seed_user(db_session, 3, role="child")
    # No matching control rule for child role → implicit deny.
    out = await check_permission(
        db_session, user_id=3, user_role="child",
        entity_id="ha:light.bedroom", action=ACTION_CONTROL,
    )
    assert out.decision == PERM_DENY


async def test_elder_can_control_lights_and_climate(db_session) -> None:
    await _seed_user(db_session, 4, role="elder")
    for entity in ("ha:light.x", "ha:climate.x", "ha:cover.x"):
        out = await check_permission(
            db_session, user_id=4, user_role="elder",
            entity_id=entity, action=ACTION_CONTROL,
        )
        assert out.decision == PERM_ALLOW, entity


async def test_elder_cannot_lock(db_session) -> None:
    await _seed_user(db_session, 4, role="elder")
    out = await check_permission(
        db_session, user_id=4, user_role="elder",
        entity_id="ha:lock.front_door", action=ACTION_LOCK,
    )
    assert out.decision == PERM_DENY


async def test_guest_can_only_query(db_session) -> None:
    await _seed_user(db_session, 5, role="guest")
    q = await check_permission(
        db_session, user_id=5, user_role="guest",
        entity_id="ha:light.cucina", action=ACTION_QUERY,
    )
    c = await check_permission(
        db_session, user_id=5, user_role="guest",
        entity_id="ha:light.cucina", action=ACTION_CONTROL,
    )
    assert q.decision == PERM_ALLOW
    assert c.decision == PERM_DENY


async def test_unknown_role_gets_guest_defaults(db_session) -> None:
    await _seed_user(db_session, 6, role="parent")
    out = await check_permission(
        db_session, user_id=6, user_role="some_unknown_role",
        entity_id="ha:light.x", action=ACTION_CONTROL,
    )
    # Fallback role matrix is _GUEST → control implicitly denies.
    assert out.decision == PERM_DENY


# --------------------------------------------------------------- explicit user rules


async def test_explicit_allow_overrides_role_deny(db_session) -> None:
    """A child gets explicit ALLOW for their bedroom light."""
    await _seed_user(db_session, 3, role="child")
    db_session.add(DevicePermission(
        user_id=3, entity_pattern="ha:light.bedroom_marco",
        action=ACTION_CONTROL, decision=PERM_ALLOW,
        reason="own room",
    ))
    await db_session.commit()

    out = await check_permission(
        db_session, user_id=3, user_role="child",
        entity_id="ha:light.bedroom_marco", action=ACTION_CONTROL,
    )
    assert out.decision == PERM_ALLOW
    assert out.matched_source == "user"
    assert out.reason == "own room"


async def test_explicit_deny_overrides_role_allow(db_session) -> None:
    """Parent normally allowed, but admin denies a specific entity."""
    await _seed_user(db_session, 1, role="parent")
    db_session.add(DevicePermission(
        user_id=1, entity_pattern="ha:light.dining_room",
        action=ACTION_CONTROL, decision=PERM_DENY,
        reason="under maintenance",
    ))
    await db_session.commit()

    out = await check_permission(
        db_session, user_id=1, user_role="parent",
        entity_id="ha:light.dining_room", action=ACTION_CONTROL,
    )
    assert out.decision == PERM_DENY
    assert out.matched_source == "user"


async def test_explicit_deny_wins_over_explicit_allow(db_session) -> None:
    """If the user has both an allow and a deny matching, deny wins."""
    await _seed_user(db_session, 2, role="teen")
    db_session.add(DevicePermission(
        user_id=2, entity_pattern="ha:light.*",
        action=ACTION_CONTROL, decision=PERM_ALLOW,
    ))
    db_session.add(DevicePermission(
        user_id=2, entity_pattern="ha:light.parent_bedroom",
        action=ACTION_CONTROL, decision=PERM_DENY,
        reason="off-limits",
    ))
    await db_session.commit()

    out = await check_permission(
        db_session, user_id=2, user_role="teen",
        entity_id="ha:light.parent_bedroom", action=ACTION_CONTROL,
    )
    assert out.decision == PERM_DENY


async def test_explicit_allow_with_more_specific_pattern_wins(db_session) -> None:
    """Two ALLOW rules at different specificity → more specific wins."""
    await _seed_user(db_session, 1, role="parent")
    db_session.add(DevicePermission(
        user_id=1, entity_pattern="ha:light.*",
        action=ACTION_CONTROL, decision=PERM_ALLOW, reason="general",
    ))
    db_session.add(DevicePermission(
        user_id=1, entity_pattern="ha:light.cucina",
        action=ACTION_CONTROL, decision=PERM_ASK, reason="confirm in kitchen",
    ))
    await db_session.commit()

    # The more specific ASK should win.
    out = await check_permission(
        db_session, user_id=1, user_role="parent",
        entity_id="ha:light.cucina", action=ACTION_CONTROL,
    )
    assert out.decision == PERM_ASK
    assert out.reason == "confirm in kitchen"


async def test_implicit_deny_when_no_rule_anywhere(db_session) -> None:
    """A guest tries to control a non-light entity → implicit deny."""
    await _seed_user(db_session, 5, role="guest")
    out = await check_permission(
        db_session, user_id=5, user_role="guest",
        entity_id="ha:fan.cucina", action=ACTION_CONTROL,
    )
    assert out.decision == PERM_DENY
    assert out.matched_source == "default"
