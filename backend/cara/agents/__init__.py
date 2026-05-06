"""Cara agents — Celery-backed background workers that handle slow,
periodic, or memory-heavy work outside the FastAPI process.

Three groups:

- `mail`   — Gmail scan + Calendar sync. Beat-driven (15 min / 5 min).
             Writes `EmailProposal` rows for the user to approve.
- `files`  — PDF / DOCX / image ingestion + OCR. On-demand, triggered
             by `POST /api/v1/files`. Writes parse output to MinIO and
             marks the `UploadedFile` row ready.
- `learn`  — habit detection + reflective batch. Beat-driven nightly /
             weekly. Writes `HabitCandidate` rows and clusters of
             routing misses for the admin to review.

The chat orchestrator NEVER calls these tasks synchronously — it
either reads from the table the agent populated, or enqueues a task
and polls. NPU is single-tenant; if an agent ever needs LLM inference
it goes through the public chat HTTP endpoint, not directly through
`LLMService`.
"""
