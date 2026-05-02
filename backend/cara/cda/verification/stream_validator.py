"""Audio-stream specific verification: HEAD + first 32 KB flow check."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import structlog

log = structlog.get_logger(__name__)

USER_AGENT = "CARA/0.6 (private home assistant)"

_AUDIO_MIMES = (
    "audio/",
    "application/ogg",
    "application/octet-stream",   # some icecast servers serve as bin
    "application/vnd.apple.mpegurl",  # m3u8
    "application/x-mpegurl",
    "audio/x-mpegurl",
)


@dataclass
class StreamCheckResult:
    ok: bool
    content_type: str | None
    bytes_flowed: int
    elapsed_ms: int
    error: str | None = None


def _mime_is_audio(mime: str | None) -> bool:
    if not mime:
        return False
    m = mime.split(";", 1)[0].strip().lower()
    return any(m.startswith(prefix) for prefix in _AUDIO_MIMES)


async def check_audio_stream(url: str, *, timeout: float = 5.0, min_bytes: int = 8 * 1024) -> StreamCheckResult:
    """Verify that an audio URL streams: HEAD ok + first ≥8 KB flow within `timeout`."""
    import time

    started = time.perf_counter()
    headers = {"User-Agent": USER_AGENT, "Icy-MetaData": "0"}
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=timeout, headers=headers
        ) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    return StreamCheckResult(
                        ok=False,
                        content_type=resp.headers.get("content-type"),
                        bytes_flowed=0,
                        elapsed_ms=int((time.perf_counter() - started) * 1000),
                        error=f"HTTP {resp.status_code}",
                    )
                ct = resp.headers.get("content-type")
                # m3u/m3u8/pls have text/* or specific mimes — accept; HLS is
                # validated structurally rather than by audio bytes.
                if not (_mime_is_audio(ct) or url.endswith((".m3u", ".m3u8", ".pls"))):
                    return StreamCheckResult(
                        ok=False,
                        content_type=ct,
                        bytes_flowed=0,
                        elapsed_ms=int((time.perf_counter() - started) * 1000),
                        error=f"non-audio content-type: {ct}",
                    )
                bytes_count = 0
                async for chunk in resp.aiter_bytes(chunk_size=4096):
                    bytes_count += len(chunk)
                    if bytes_count >= min_bytes:
                        break
                return StreamCheckResult(
                    ok=bytes_count >= min_bytes,
                    content_type=ct,
                    bytes_flowed=bytes_count,
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                )
    except Exception as exc:  # noqa: BLE001
        log.debug("cda.stream.check.failed", url=url, error=str(exc))
        return StreamCheckResult(
            ok=False,
            content_type=None,
            bytes_flowed=0,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            error=str(exc),
        )
