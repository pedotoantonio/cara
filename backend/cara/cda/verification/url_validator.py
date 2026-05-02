"""Generic HTTP HEAD/GET probes."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import structlog

log = structlog.get_logger(__name__)

USER_AGENT = "CARA/0.6 (private home assistant)"


@dataclass
class UrlCheckResult:
    ok: bool
    status: int | None
    content_type: str | None
    final_url: str | None
    error: str | None = None


async def check_url(url: str, timeout: float = 4.0) -> UrlCheckResult:
    """HEAD probe; falls back to GET (range 0-1024) if HEAD is rejected."""
    headers = {"User-Agent": USER_AGENT}
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=timeout, headers=headers
        ) as client:
            try:
                r = await client.head(url)
                if r.status_code in (405, 501):
                    raise httpx.HTTPStatusError("method not allowed", request=r.request, response=r)
                return UrlCheckResult(
                    ok=200 <= r.status_code < 400,
                    status=r.status_code,
                    content_type=r.headers.get("content-type"),
                    final_url=str(r.url),
                )
            except (httpx.HTTPStatusError, httpx.UnsupportedProtocol):
                pass
            r = await client.get(url, headers={**headers, "Range": "bytes=0-1023"})
            return UrlCheckResult(
                ok=200 <= r.status_code < 400,
                status=r.status_code,
                content_type=r.headers.get("content-type"),
                final_url=str(r.url),
            )
    except Exception as exc:  # noqa: BLE001
        log.debug("cda.url.check.failed", url=url, error=str(exc))
        return UrlCheckResult(ok=False, status=None, content_type=None, final_url=None, error=str(exc))
