"""Smoke tests for /api/v1/tools/* (tool-call telemetry from the frontend)."""

from __future__ import annotations

import httpx
import pytest


pytestmark = pytest.mark.asyncio


async def test_record_metric_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.post(
        "/api/v1/tools/metric",
        json={"parse_ok": True, "name_match": True, "args_valid": True, "executed": True},
    )
    assert r.status_code == 401, r.text


async def test_record_full_success_attempt(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/api/v1/tools/metric",
        json={
            "parse_ok": True,
            "name_match": True,
            "args_valid": True,
            "executed": True,
            "tool_name": "add_task",
            "duration_ms": 17,
            "conversation_id": "smoke-test-conv",
        },
    )
    assert r.status_code == 204, r.text


async def test_record_parse_failure_with_typo_prefix(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.post(
        "/api/v1/tools/metric",
        json={
            "parse_ok": False,
            "tool_name": None,
            "error_class": "typo_prefix",
            "raw_call": "TUTOOL: add_task(title=\"x\")",
        },
    )
    assert r.status_code == 204, r.text


async def test_record_metric_validates_duration_range(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.post(
        "/api/v1/tools/metric",
        json={"parse_ok": True, "duration_ms": -50},  # ge=0
    )
    assert r.status_code == 422, r.text


async def test_record_metric_validates_raw_call_length(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.post(
        "/api/v1/tools/metric",
        json={"parse_ok": False, "raw_call": "x" * 5000},  # > 2000
    )
    assert r.status_code == 422, r.text


async def test_error_classes_endpoint_lists_known_slugs(
    auth_client: httpx.AsyncClient,
) -> None:
    r = await auth_client.get("/api/v1/tools/error-classes")
    assert r.status_code == 200, r.text
    body = r.json()
    items = set(body["items"])
    # Sanity: the canonical slugs are all present.
    expected = {
        "typo_prefix", "parse_malformed", "unknown_tool", "missing_arg",
        "schema_invalid", "permission_denied", "exec_exception",
    }
    assert expected.issubset(items)


async def test_error_classes_requires_auth(http: httpx.AsyncClient) -> None:
    r = await http.get("/api/v1/tools/error-classes")
    assert r.status_code == 401, r.text
