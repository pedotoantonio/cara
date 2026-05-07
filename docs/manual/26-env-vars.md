# Cap 26 — Riferimento variabili `.env`

> *Sintesi 30 secondi.* Tutte le variabili `.env` di CARA, tabellate per
> dominio. Solo **secret e parametri statici** vivono qui (per i flag
> runtime modificabili dall'admin, vedi cap 27).

Il `.env` viene letto da pydantic-settings al boot del backend. Modifiche
richiedono restart container.

## 26.1 Ambiente

| Variabile | Default | Descrizione |
|---|---|---|
| `CARA_ENV` | `development` | `development` espone Swagger su `/api/docs`; `production` lo disabilita |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `UVICORN_WORKERS` | `1` | **Non alzare**: NPU contesa fra workers |

## 26.2 Database e cache

| Variabile | Default | Descrizione |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://cara:cara@postgres:5432/cara` | URL Postgres async |
| `REDIS_URL` | `redis://redis:6379/0` | URL Redis |
| `MINIO_ENDPOINT` | `minio:9000` | Endpoint S3 |
| `MINIO_ROOT_USER` | `cara` | Username MinIO |
| `MINIO_ROOT_PASSWORD` | (random) | Password MinIO (≥32 byte random) |
| `CHROMA_HOST` | `chroma` | ChromaDB host |
| `CHROMA_PORT` | `8000` | ChromaDB port |

## 26.3 Auth + sicurezza

| Variabile | Default | Descrizione |
|---|---|---|
| `JWT_SECRET` | (random) | Firma JWT HS256 (32+ byte) |
| `JWT_ALGORITHM` | `HS256` | Sempre HS256 |
| `JWT_ACCESS_TTL_MINUTES` | `60` | Scadenza access token |
| `JWT_REFRESH_TTL_DAYS` | `30` | Scadenza refresh token |
| `OAUTH_ENCRYPTION_KEY` | (vuoto, opzionale) | 32-byte hex per AES-GCM su OAuth tokens |

> **🔒 Sicurezza** — `JWT_SECRET` e `OAUTH_ENCRYPTION_KEY` sono i due
> segreti più importanti. Backuppali insieme al DB. Se li perdi: tutti
> i JWT scadono + OAuth tokens cifrati irrecuperabili.

## 26.4 LLM

| Variabile | Default | Descrizione |
|---|---|---|
| `LLM_MODEL_PATH` | `/app/models/qwen2.5-1.5b-instruct-w8a8.rkllm` | File modello |
| `LLM_LIB_PATH` | `/usr/lib/rkllm/librkllmrt.so` | Runtime RKLLM |
| `LLM_MAX_NEW_TOKENS` | `512` | Default lunghezza risposta |
| `LLM_TEMPERATURE` | `0.45` | Sampling temperature |
| `LLM_TOP_P` | `0.85` | Sampling top-p |
| `LLM_TOP_K` | `40` | Sampling top-k |
| `LLM_REPEAT_PENALTY` | `1.05` | Anti-ripetizione |
| `KV_CACHE_DIR` | `/app/cache/kv` | Path KV cache files |

## 26.5 TTS / STT

| Variabile | Default | Descrizione |
|---|---|---|
| `TTS_ENABLED` | `true` | Abilita Piper TTS |
| `TTS_VOICES_DIR` | `/app/tts/piper/voices` | Path voci Piper |
| `TTS_DEFAULT_VOICE` | `it_IT-paola-medium` | Voce default |
| `TTS_CACHE_TTL_SECONDS` | `3600` | Cache Redis 1h |
| `TTS_CACHE_MAX_CHARS` | `2000` | Solo testi sotto 2000 char vanno in cache |
| `WHISPER_MODEL_NAME` | `small` | `tiny`/`base`/`small`/`medium` |
| `WHISPER_CACHE_DIR` | `/app/whisper-cache` | Cache HuggingFace |

## 26.6 Integrazioni Google

| Variabile | Default | Descrizione |
|---|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` | (vuoto) | Da console.cloud.google.com |
| `GOOGLE_OAUTH_CLIENT_SECRET` | (vuoto) | Da console.cloud.google.com |
| `GOOGLE_OAUTH_REDIRECT_URI` | (auto) | `https://192.168.1.23:8455/api/v1/oauth/google/callback` |
| `CALENDAR_SYNC_INTERVAL_SECONDS` | `300` | Pull Calendar ogni 5 min |
| `GMAIL_SCAN_INTERVAL_SECONDS` | `600` | Scan Gmail ogni 10 min |

## 26.7 Push notifications (VAPID)

| Variabile | Default | Descrizione |
|---|---|---|
| `VAPID_PUBLIC_KEY` | (vuoto) | Generato da setup wizard |
| `VAPID_PRIVATE_KEY` | (vuoto) | Generato da setup wizard |
| `VAPID_SUBJECT` | (vuoto) | `mailto:tu@example.com` |
| `PUSH_SCHEDULER_INTERVAL_SECONDS` | `60` | Tick scheduler reminder |

Se i 3 VAPID sono vuoti, il scheduler **non parte** (log
`cara.push_scheduler_skipped reason=vapid_not_configured`).

## 26.8 Cloud LLM (DEFERRED)

| Variabile | Default | Descrizione |
|---|---|---|
| `ANTHROPIC_API_KEY` | (vuoto) | Per Skill Author + email NLU layer 3 |
| `SKILL_AUTHOR_PROVIDER` | `anthropic` | Provider |
| `SKILL_AUTHOR_MODEL` | `claude-haiku-4-5` | Modello |

Mai contattati senza `cloud_llm_enabled=true` in `admin_settings`.

## 26.9 Telegram bot

| Variabile | Default | Descrizione |
|---|---|---|
| `CARA_TELEGRAM_BOT_TOKEN` | (vuoto) | Da BotFather |
| `CARA_TELEGRAM_ALLOWED_CHAT_IDS` | (vuoto) | CSV di chat_id autorizzati |

Se vuoti, bot non parte.

## 26.10 CDA

| Variabile | Default | Descrizione |
|---|---|---|
| `CDA_SEARXNG_URL` | `https://searxng.tutorialfm.com/` | Istanza SearXNG |
| `CDA_RATE_LIMIT_CAPACITY` | `10` | Token bucket size |
| `CDA_RATE_LIMIT_REFILL_PER_SEC` | `0.5` | Refill rate |
| `CDA_MAINTENANCE_INTERVAL_SECONDS` | `21600` | Job pulizia ogni 6h |

## 26.11 Smart home

| Variabile | Default | Descrizione |
|---|---|---|
| `HA_DEFAULT_URL` | `http://172.31.0.1:8123` | Default HA URL (configurabile da admin) |
| `HA_EVENTS_RECONNECT_SECONDS` | `30` | Backoff WebSocket reconnect |

## 26.12 Frigate

| Variabile | Default | Descrizione |
|---|---|---|
| `FRIGATE_URL` | `http://172.31.0.11:5000` | URL Frigate API |
| `FRIGATE_WEBHOOK_SECRET` | (vuoto) | Per webhook custom |
| `FRIGATE_FACES_URL` | `http://192.168.1.23:8452` | URL frigate-faces |

## 26.13 Proactivity

| Variabile | Default | Descrizione |
|---|---|---|
| `PROACTIVITY_SCHEDULER_INTERVAL_SECONDS` | `600` | Tick ogni 10 min |
| `PROACTIVITY_SILENT_HOURS_START` | `22` | Inizio silent hours |
| `PROACTIVITY_SILENT_HOURS_END` | `7` | Fine silent hours |

## 26.14 Test

| Variabile | Default | Descrizione |
|---|---|---|
| `CARA_TEST_BASE_URL` | `https://192.168.1.23:8455` | Target smoke tests |
| `CARA_TEST_ADMIN_EMAIL` | `pedotoa@gmail.com` | Per `admin_client` fixture |
| `CARA_TEST_ADMIN_PASSWORD` | `caracasa2026` | Idem |
| `PWBASE` | (uguale a CARA_TEST_BASE_URL) | Per Playwright E2E |
| `PW_ADMIN_EMAIL` | (idem) | Per Playwright `loggedInPage` |
| `PW_ADMIN_PASSWORD` | (idem) | Idem |

## 26.15 Esempio `.env` minimo

Per far partire CARA in sviluppo:

```ini
CARA_ENV=development
DATABASE_URL=postgresql+asyncpg://cara:cara@postgres:5432/cara
REDIS_URL=redis://redis:6379/0
MINIO_ENDPOINT=minio:9000
MINIO_ROOT_USER=cara
MINIO_ROOT_PASSWORD=changeme-32+chars-please
JWT_SECRET=changeme-32+chars-please
```

Per produzione famiglia, aggiungi:

```ini
OAUTH_ENCRYPTION_KEY=<openssl rand -hex 32>
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...
VAPID_PUBLIC_KEY=...
VAPID_PRIVATE_KEY=...
VAPID_SUBJECT=mailto:antonio@example.com
```

---

[← Cap 25 Estendere CARA](25-estendere-cara.md) · [README](README.md) · [Cap 27 Riferimento admin_settings →](27-admin-settings.md)
