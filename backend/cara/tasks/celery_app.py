"""Celery application — single instance shared by all agent workers.

CARA splits long-running / heavy work out of the FastAPI process into
Celery workers. The chat orchestrator must NEVER block on I/O > 1s
(NPU is single-tenant and SSE streams are sensitive to event loop
delay), so anything slow runs as a Celery task and writes its output
to Postgres / publishes on the family bus when done.

Three logical worker groups, each one container with `--concurrency=1`
to keep memory bounded on the NanoPC:

- `mail`       — Gmail scan + Calendar sync (scheduled, beat)
- `files`      — PDF / DOCX / image ingestion + OCR (on-demand)
- `learn`      — habit detection + reflective batch (scheduled, beat)

The `cara-celery-beat` container drives the scheduled tasks. Workers
listen only on the queue matching their group so a slow file
ingestion doesn't block a mail scan, and vice versa.

Broker: Redis (already running). Result backend: same Redis db (small
result payloads, the canonical state lives in Postgres tables like
`agent_runs` and `email_proposals`).
"""

from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

from cara.config import settings


_REDIS_BASE = settings.redis_url.rstrip("/")


celery_app = Celery(
    "cara",
    broker=f"{_REDIS_BASE}/1",
    backend=f"{_REDIS_BASE}/2",
    include=[
        "cara.agents.mail",
        "cara.agents.files",
        "cara.agents.learn",
        "cara.agents.presence",
    ],
)

celery_app.conf.update(
    task_default_queue="default",
    task_routes={
        "cara.agents.mail.*": {"queue": "mail"},
        "cara.agents.files.*": {"queue": "files"},
        "cara.agents.learn.*": {"queue": "learn"},
        "cara.agents.presence.*": {"queue": "presence"},
    },
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Rome",
    enable_utc=True,
    # Per-task hard timeout (5 min) and soft timeout (4:30) — agents
    # must finish or persist a partial state, never block the queue.
    task_time_limit=300,
    task_soft_time_limit=270,
    # Keep results around for 1 hour so /admin/agents can show them,
    # then drop. Long-term history lives in `agent_runs` table.
    result_expires=3600,
    # Bound how much each worker can hold so a leak in one task
    # doesn't drift the container OOM.
    worker_max_tasks_per_child=200,
    worker_max_memory_per_child=512_000,  # 512 MB
)


# ─── Beat schedule ──────────────────────────────────────────────────
#
# Times are Europe/Rome (configured above). Schedules tuned for a
# household: don't hammer Google during chat hours, run heavy batches
# overnight when the family is asleep.

celery_app.conf.beat_schedule = {
    # Presence group — the most latency-sensitive: 30 s gives an
    # acceptable "X is home" delay without spamming frigate-faces.
    "presence-poll-every-30-sec": {
        "task": "cara.agents.presence.poll_arrivals",
        "schedule": 30,
    },
    # Mail group — frequent because users expect a fresh view on the
    # phone, and Gmail polling cost is low.
    "scan-gmail-every-15-min": {
        "task": "cara.agents.mail.scan_gmail",
        "schedule": 15 * 60,          # 15 minutes
    },
    "sync-calendar-every-5-min": {
        "task": "cara.agents.mail.sync_calendar",
        "schedule": 5 * 60,           # 5 minutes
    },
    # Learn group — overnight only. The 1.5B is asleep, frigate is
    # quieter (less people moving → fewer detections), and any heavy
    # CPU spike doesn't impact a real user.
    "habit-detection-nightly": {
        "task": "cara.agents.learn.detect_habits",
        "schedule": crontab(hour=3, minute=0),
    },
    "reflective-batch-weekly": {
        "task": "cara.agents.learn.reflective_run",
        "schedule": crontab(hour=4, minute=0, day_of_week="sunday"),
    },
}


# ─── Optional flag — disable in unit tests ──────────────────────────

if os.environ.get("CARA_CELERY_ALWAYS_EAGER", "").lower() in ("1", "true", "yes"):
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
