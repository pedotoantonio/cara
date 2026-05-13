# CARA — Changelog

All notable changes to CARA. Dates in `YYYY-MM-DD`. The Step / Epic
numbering follows the v1.0 development plan in
`docs/HANDOFF-v1.0-epic-0-1.md`. Day-by-day historic notes for the
pre-v1.0 period are in `~/CARA-CHANGELOG.md`.

## [Unreleased]

### Added — Face Recognition (privacy-first, on-device)

A complete face recognition stack mounted at `/face/enroll` (wizard)
and `/admin/face` (governance). All inference happens in a Web Worker
inside the browser via `@vladmandic/face-api`; the backend only stores
128-D descriptors (`pgvector` `vector(128)`). No raw images cross the
wire. The feature defaults to **disabled**; admin opt-in required.

Delivered across 7 phases:

- **Phase 1 — Foundations.** `@vladmandic/face-api` + `idb-keyval`
  deps; same-origin model weights in `public/models/face-api/` (7.1
  MB, cache-first SW); `tinyFaceDetector` Web Worker scaffold;
  `FaceProvider` + `useFaceDetection` hook + `FaceOverlay` SVG;
  backend tables `face_profiles`, `face_descriptors`, `face_settings`
  with HNSW cosine index; admin-only REST CRUD at `/api/v1/face/`.
- **Phase 2 — Recognition.** Lazy `landmark68` + `recognition`
  model load (~6.8 MB); 128-D descriptor per detection; local match
  against an in-memory profile cache; ambiguity guard drops the
  match when second-best is within 0.05; temporal smoothing (3
  frames / 1 s → confirm; 2 s → lost); new endpoints
  `POST/GET /face/profiles/{id}/descriptors` + `POST /face/match`;
  retention cap of 30 descriptors per profile.
- **Phase 3 — Enrollment wizard.** 6-step user flow with live
  quality scoring, auto-capture on 3 consecutive frames ≥ 0.8, and
  a 4/5-pass save gate.
- **Phase 4 — Admin panel.** `/admin/face` with stats, global
  settings, profile table (rename / threshold / child / active),
  and 2-click delete confirm.
- **Phase 5 — Multi-face + child mode hooks.** Cap of 4 tracked
  faces; `primarySubject` + `companions`; new `ActiveProfileContext`
  with sessionStorage persistence; `data-cara-child-mode` on
  `<html>`; client-side smart-home permission gate blocking
  dangerous actions in child mode.
- **Phase 6 — Performance + robustness.** Adaptive throttle
  (rolling 10-sample latency average, clamped 50–1000 ms); idle
  mode (30 s no face → 1 FPS); anti-spoofing (centroid variance
  < 3 px / 1 s → likely photo); continuous learning (every 50
  confirmed frames → POST a `continuous` descriptor).
- **Phase 7 — Tests, debug, docs.** Backend smoke suite
  (`tests/smoke/test_face_api.py`, 7 tests); Vitest unit suites
  (10 tests) wired into `npm test`; live diagnostics at
  `/admin/face/debug`; IT user docs + developer docs.

### Removed

- `chroma` references that lingered after the container itself was
  retired: probe in `cara/agents/health.py` (was failing every 5 min
  with `ConnectError`); `chroma_host` + `chroma_port` settings; stale
  "9 probes" comment in `admin_settings.py`; CLAUDE.md table entries.
  Health tick is now 8/8 ok on a clean stack.

### Fixed

- Schema drift between SQLAlchemy models and the live Postgres: the
  `tasks.calendar_external_id` column, the `skills_name_uniq` /
  `skills_status_idx` indexes, and the three `cda_*` performance
  indexes are now declared in the ORM models. `alembic check`
  reports "No new upgrade operations detected".

## [1.0.0] — 2026-05-05

First public release. Replaces the Step-66 working tree with a
production-ready v1.0 covering all 11 Epic of the original roadmap,
except Cloud Haiku (DEFERRED) and the physical Hardware Wall
(planned Mese 6).

### Added

- **Epic 0 — Foundations**
  - E2E HTTP smoke harness (`tests/smoke/`) + in-memory unit harness
  - Episodic memory persisted in Postgres (`events`)
  - Tool-call telemetry funnel (`tool_call_metrics`) with 7 canonical
    error classes
  - Router `Pipeline` with per-stage telemetry hook
  - `chat.py` refactor 1322 → 807 lines (-39%)
  - RKLLM KV cache reuse via `prompt_cache_path` — TTFT 8.3× faster
    on follow-up turns

- **Epic 1 — Voce**
  - ~300 Italian anglicism normalizations + admin override API
    (`/admin/tts/overrides`) with hot-swap
  - Sentence-buffered TTS streaming (`audio_chunk` SSE event) +
    frontend WebAudio queue → first audio plays in ~2 s instead of
    waiting for full reply
  - Response cache Redis keyed by message + role + settings fingerprint
  - Segmented system prompt (base + tone + facts) with stable-prefix
    fingerprint for KV cache invalidation

- **Epic 2 — Memoria**
  - Multilingual MiniLM embedding service (lazy + Redis-cached)
  - Italian NER (spaCy + 7 PII regexes + family glossary)
  - Semantic facts (extraction + retrieval) — 7 fact types, top-k
    cosine for prompt injection
  - `/me/memoria` UI (CRUD + GDPR export/purge), admin viewer

- **Epic 3 — Workflow**
  - OCR (Tesseract + OpenCV preprocessing + amount detector)
  - ReceiptWorkflow, BillWorkflow, RecipeWorkflow with auto-confirm
    trust streak per `(user, workflow, signature)`
  - REST `/workflows/run` + frontend WorkflowPreview component
  - Offline queue (IndexedDB) for replaying writes

- **Epic 4 — Skill Factory** (this release)
  - **Phase B** — generic primitives: `extract_list`, `summarize`,
    `ask_user`, `read_url` (composable into JSON skills without writing
    Python)
  - **Phase C** — multi-tier dispatcher: regex (Tier-1) → cosine
    embedding (Tier-2) → local LLM classifier (Tier-3, opt-in). Tier
    + confidence emitted into `router.skill_hit` episodic events.
  - **Phase E** — `/admin/skills` UI with tabs (pending/active/disabled),
    JSON editor with live primitive catalog inline, validation against
    the registry before persisting
  - PATCH endpoint with audited version bump, dispatcher cache
    invalidation, plan.steps[].tool validated against the live
    primitive registry

- **Epic 5 — Smart Home**
  - Provider-agnostic `SmartHomeAdapter` Protocol + canonical entity
    ids (`<provider>:<local_id>`)
  - HomeAssistant REST adapter + WebSocket events subscriber (writes
    `ha.state_changed` to episodic)
  - 4-stage NLU (intent regex → alias exact → substring → embedding
    fallback) + presence disambiguation
  - Per-user device permissions with deny/ask/allow + role defaults
  - Admin device-aliases endpoint
  - `/admin/smart-home` UI

- **Epic 6 — Multi-device** (this release)
  - 6-digit pairing flow (`/pair` anonymous page → `/admin/devices`
    finalize → device JWT minted, single-use Redis ticket)
  - 5 surface classes (mobile, desktop, wall, watch, tv); the Wallet
    engine already honours per-surface caps
  - Admin device list with rename / change-surface / disable / delete
  - Heartbeat endpoint for paired devices

- **Epic 7 — Wallet**
  - Widget engine + 13 catalogued widgets (today_summary, tasks_mine,
    shopping_quick, notes_recent, weather_now, presence,
    quick_actions, budget_month, kids_homework, routine_next,
    cara_quote, news_brief, radio_now_playing)
  - Per-user, per-surface layout persistence
  - 4 preset profiles (parent/teen/child/elder)
  - Frontend WalletPage + WidgetCard

- **Epic 8 — Proattività**
  - Open-Meteo weather + WMO icon mapping (27 codes)
  - Deterministic habit detection (3-hour bucket, 30-day lookback)
  - Reflective batch (cosine cluster of router misses + tool-failure
    classes)
  - Engine with rule isolation, cooldown, silent hours overnight-wrap
  - **10 concrete rules**: morning_greeting, undone_tasks_evening,
    rain_alert, door_open_long, bedtime_routine, birthday_today,
    shopping_review_saturday, task_overdue_24h, budget_drift_warning,
    lights_on_nobody_home

- **Integrations** (this release)
  - VAPID Web Push reminders + scheduler
  - Family-bus WebSocket sync (Redis pub/sub) for live multi-device
    updates
  - Google Calendar two-way sync (pull + push, prevents echo loop via
    `extendedProperties.private.cara_managed=1`)
  - Gmail readonly + 3-layer email NLU (deterministic IT regex →
    1.5B local → cloud Haiku DEFERRED). 4-level read-only guarantee
    (OAuth scope + API surface + docstring + grep regression test)
  - AES-256-GCM token storage at rest

- **Frontend / Design**
  - Day/night design system: terracotta+avorio+sage day,
    blu-notte+ambra night, 29 custom SVG icons, Card / Button / Input
    / Toast / BottomSheet primitives
  - PWA v1.0.0 with manifest shortcuts (Voce, Task, Spesa, Wallet)
  - mkcert local CA bundle published at `/cara-ca.crt` so families
    install it once and Chrome treats `192.168.1.23:8455` as fully
    trusted (enables the native PWA install prompt)
  - InstallPwaPrompt with 3 paths (native / iOS / fallback) + manual
    re-trigger button on Settings

- **Tooling / Ops**
  - LoRA dataset extractor (`scripts/export_lora_dataset.py`) +
    RunPod training runbook (`scripts/lora-train-runpod.sh`)
  - 18 hand-curated synthetic tool-call training examples
  - Backup + KV-cache cleanup helpers in `scripts/`
  - Italian family + admin manuals in `docs/`
  - 5 Playwright E2E specs covering smoke, tasks, PWA install, admin
    skills, and pairing

### Tests

- **641 backend unit tests** (in-memory SQLite + httpx mocks)
- **Smoke suite** ~120 tests against the live backend
- **Playwright E2E** 5 specs (admin Mac/Windows machine — Chromium
  arm64 not supported on aarch64 Linux)

### Deferred

- **Cloud Haiku** — architecture has the hooks (`cloud_llm.py`,
  `cloud.enabled=False`); flip on when the family wants stronger
  reasoning at predictable cost. Email NLU layer-3 + skill-author
  Phase D both wire through here.
- **Hardware Wall** (Raspberry Pi 5 7" touchscreen, BoM ~€450) —
  needs the physical install at home; software side already supports
  the surface (`surface_class=wall`).

### Known limitations

- Tool-calling reliability ~60-70% on the 1.5B base; LoRA pipeline
  shipped but not yet executed (~$5 RunPod, 5 h GPU). Tier-3 LLM
  classifier helps once enabled.
- Skill Factory Phase F (migrating remaining hardcoded intents to JSON
  skills) and Phase G are post-1.0 work.
