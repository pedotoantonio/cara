"""Admin diagnostics endpoints.

Three flavours:
- GET  /admin/diagnostics                 — run all health checks
- GET  /admin/diagnostics/events          — recent voice events ring buffer
- GET  /admin/diagnostics/log?lines=N     — tail of the persistent JSONL log
- POST /admin/diagnostics/test/speak      — server-side speak test
- POST /admin/diagnostics/test/llm        — quick LLM round-trip
- POST /admin/diagnostics/test/discover   — CDA discover smoke
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import require_admin
from cara.cda import CdaError, DiscoverRequest, discover as cda_discover
from cara.config import settings
from cara.models.user import User
from cara.services import diagnostics as diag_svc
from cara.services import event_log
from cara.store import get_session

router = APIRouter(prefix="/admin/diagnostics", tags=["admin", "diagnostics"])


@router.get("")
async def diagnostics_overview(
    _admin: User = Depends(require_admin),  # noqa: B008
) -> dict[str, Any]:
    checks = await diag_svc.run_all()
    summary = {"ok": 0, "warn": 0, "error": 0}
    for c in checks:
        summary[c["status"]] = summary.get(c["status"], 0) + 1
    return {
        "checks": checks,
        "summary": summary,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


@router.get("/events")
async def diagnostics_events(
    limit: int = 100,
    kind: str | None = Query(None),
    _admin: User = Depends(require_admin),  # noqa: B008
) -> dict[str, Any]:
    kinds = [k.strip() for k in kind.split(",")] if kind else None
    return {
        "events": event_log.recent(limit=limit, kinds=kinds),
        "stats": event_log.stats(),
    }


@router.delete("/events")
async def diagnostics_events_clear(
    _admin: User = Depends(require_admin),  # noqa: B008
) -> dict[str, str]:
    event_log.clear()
    return {"status": "cleared"}


@router.get("/log")
async def diagnostics_log(
    lines: int = 200,
    _admin: User = Depends(require_admin),  # noqa: B008
) -> Response:
    """Tail of today's structlog JSONL file (when log persistence is on)."""
    log_dir = Path("/app/logs")
    if not log_dir.exists():
        return Response(content="(log directory missing)\n", media_type="text/plain")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    candidates = sorted(log_dir.glob("cara-*.jsonl"), reverse=True)
    if not candidates:
        return Response(content="(no log files yet)\n", media_type="text/plain")
    target = candidates[0]
    try:
        size = os.path.getsize(target)
        # Read up to ~256 KB from the tail.
        cap = min(size, 256 * 1024)
        with target.open("rb") as f:
            f.seek(max(0, size - cap))
            data = f.read().decode("utf-8", errors="replace")
        out_lines = data.splitlines()[-max(1, lines):]
        return Response(content="\n".join(out_lines) + "\n", media_type="application/x-ndjson")
    except OSError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc


# ---- self-tests (admin-triggered, side-effects: write to event_log) ----


class _TestSpeak(BaseModel):
    text: str = "CARA test, mi senti?"


@router.post("/test/speak")
async def test_speak(
    body: _TestSpeak,
    _admin: User = Depends(require_admin),  # noqa: B008
) -> dict[str, Any]:
    from cara.ai.tts import get_tts_service

    t0 = time.perf_counter()
    svc = get_tts_service()
    wav, sr = await svc.synthesize_wav(text=body.text, speed=1.0)
    elapsed = int((time.perf_counter() - t0) * 1000)
    event_log.record("diag.test.speak", duration_ms=elapsed, text=body.text, bytes=len(wav))
    return {"text": body.text, "wav_bytes": len(wav), "sample_rate": sr, "elapsed_ms": elapsed}


class _TestLlm(BaseModel):
    prompt: str = "Rispondi soltanto OK"
    max_new_tokens: int = 16


@router.post("/test/llm")
async def test_llm(
    body: _TestLlm,
    _admin: User = Depends(require_admin),  # noqa: B008
) -> dict[str, Any]:
    from cara.ai.llm import get_llm_service

    svc = get_llm_service()
    rendered = (
        f"<|im_start|>system\nTi chiami CARA. Rispondi in italiano.\n<|im_end|>\n"
        f"<|im_start|>user\n{body.prompt}\n<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )
    t0 = time.perf_counter()
    t_first: float | None = None
    n = 0
    buf: list[str] = []
    async for chunk in svc.generate(rendered, max_new_tokens=body.max_new_tokens):
        if t_first is None:
            t_first = time.perf_counter() - t0
        n += 1
        buf.append(chunk.text)
    total = time.perf_counter() - t0
    text = "".join(buf).strip()
    event_log.record(
        "diag.test.llm",
        duration_ms=int(total * 1000),
        ttft_ms=int((t_first or 0.0) * 1000),
        tokens=n,
        text_chars=len(text),
        mode=svc.mode,
    )
    return {
        "text": text,
        "tokens": n,
        "ttft_s": round(t_first or 0.0, 3),
        "total_s": round(total, 2),
        "tok_per_s": round(n / max(total, 1e-6), 2),
        "mode": svc.mode,
    }


class _TestDiscover(BaseModel):
    query: str = "meteo Roma"
    kind: str = "article"


@router.post("/test/discover")
async def test_discover(
    body: _TestDiscover,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        res = await cda_discover(
            session,
            DiscoverRequest(
                user_id=admin.id, raw_query=body.query, content_type=body.kind  # type: ignore[arg-type]
            ),
        )
    except CdaError as exc:
        elapsed = int((time.perf_counter() - t0) * 1000)
        event_log.record("diag.test.discover.fail", duration_ms=elapsed, error=str(exc))
        return {"ok": False, "error": str(exc), "elapsed_ms": elapsed}
    elapsed = int((time.perf_counter() - t0) * 1000)
    event_log.record(
        "diag.test.discover.ok",
        duration_ms=elapsed,
        cached=res.cached,
        domain=res.source_domain,
    )
    return {
        "ok": True,
        "url": res.url,
        "title": res.title,
        "source_domain": res.source_domain,
        "cached": res.cached,
        "elapsed_ms": elapsed,
    }


