# Cap 28 — Riferimento API REST

> *Sintesi 30 secondi.* Tutti gli endpoint REST di CARA. Path
> `/api/v1/...`, autenticazione Bearer JWT salvo dove segnato `(anon)`.
> Per il dettaglio tipi request/response, apri Swagger su
> `https://192.168.1.23:8455/api/docs` (solo se `CARA_ENV=development`).

Il backend ha 35+ router. Qui mostriamo solo gli endpoint principali
raggruppati per dominio.

## 28.1 Health

```
GET  /health                        (anon)
GET  /api/v1/ping                   (anon)
GET  /api/v1/chat/health
GET  /api/v1/diagnostics/health     (admin)
POST /api/v1/diagnostics/self-test (admin)
```

## 28.2 Auth

```
POST /api/v1/auth/register          (anon)
POST /api/v1/auth/login              (anon)
POST /api/v1/auth/refresh            (refresh token)
GET  /api/v1/auth/me
PATCH /api/v1/auth/me                (full_name, birth_date)
POST /api/v1/auth/change-password
```

## 28.3 Chat + conversazioni

```
POST /api/v1/chat                    (SSE streaming)
GET  /api/v1/conversations
POST /api/v1/conversations
GET  /api/v1/conversations/{id}
DELETE /api/v1/conversations/{id}
```

Eventi SSE: `meta` (conversation_id), `token` (token_id+text),
`audio_chunk` (base64 WAV), `revision` (token rivisto da agent loop),
`done` (final stats), `error`.

## 28.4 Task / spesa / note

```
GET    /api/v1/tasks
POST   /api/v1/tasks
PATCH  /api/v1/tasks/{id}
DELETE /api/v1/tasks/{id}

GET    /api/v1/shopping
POST   /api/v1/shopping
PATCH  /api/v1/shopping/{id}
DELETE /api/v1/shopping/{id}
POST   /api/v1/shopping/clear-bought

GET    /api/v1/notes
POST   /api/v1/notes
PATCH  /api/v1/notes/{id}
DELETE /api/v1/notes/{id}
```

## 28.5 News / radio / weather

```
GET /api/v1/news                     (RSS aggregator)
GET /api/v1/radio                    (lista stazioni)
GET /api/v1/radio/{id}               (stream URL)

GET /api/v1/weather/geocode?q=
GET /api/v1/weather/current?lat=&lon=&timezone=
GET /api/v1/weather/forecast?lat=&lon=&days=
```

## 28.6 Voice

```
GET  /api/v1/voice/voices            (lista Piper)
GET  /api/v1/voice/default
GET  /api/v1/voice/config
POST /api/v1/voice/synthesize        (text → WAV)

POST /api/v1/asr/transcribe          (audio → text via Whisper)
```

## 28.7 Family

```
GET /api/v1/family/who-is-home       (da frigate-faces)
WS  /api/v1/family/ws?token=         (WebSocket bus)
```

## 28.8 Files

```
GET    /api/v1/files
POST   /api/v1/files                  (multipart upload)
GET    /api/v1/files/{id}
DELETE /api/v1/files/{id}
GET    /api/v1/files/{id}/download
```

I file vengono ingestiti per chat (RAG basic) — solo testuali (PDF,
DOCX, TXT, MD, CSV, XLSX, JSON, YAML).

## 28.9 Memory

```
GET    /api/v1/memory/facts
POST   /api/v1/memory/facts          (manual pin)
PATCH  /api/v1/memory/facts/{id}
DELETE /api/v1/memory/facts/{id}      (soft-delete)
POST   /api/v1/memory/facts/extract   (pattern detector)
GET    /api/v1/memory/export           (GDPR JSON)
DELETE /api/v1/memory/purge            (hard-delete tutti)
```

## 28.10 Wallet + widgets

```
GET   /api/v1/widgets                  (catalog filtrato per role)
GET   /api/v1/widgets/render?ids=&surface=&size=
GET   /api/v1/widgets/{id}              (single render)

GET   /api/v1/wallet/layout?surface=
PUT   /api/v1/wallet/layout
DELETE /api/v1/wallet/layout?surface=
GET   /api/v1/wallet/presets
POST  /api/v1/wallet/preset/{slug}
```

## 28.11 Smart home

```
GET  /api/v1/smarthome/entities
GET  /api/v1/smarthome/entities/{id:path}/state
GET  /api/v1/smarthome/scenes
GET  /api/v1/smarthome/health
POST /api/v1/smarthome/services
POST /api/v1/smarthome/resolve         (NLU dry-run)
```

## 28.12 Budget + spese

```
GET   /api/v1/budgets
PUT   /api/v1/budgets/{year}/{month}/{category}
GET   /api/v1/budgets/{year}/{month}/rollup

POST   /api/v1/expenses
GET    /api/v1/expenses
DELETE /api/v1/expenses/{id}
```

## 28.13 Workflow

```
POST /api/v1/workflows/run             (classify→propose)
POST /api/v1/workflows/execute         (esegui actions confermate)
GET  /api/v1/workflows/trust           (lista trust streak)
DELETE /api/v1/workflows/trust/{id}    (revoca)
```

## 28.14 Skill (admin)

```
GET    /api/v1/admin/skills
POST   /api/v1/admin/skills/author     (cloud LLM, opt-in)
GET    /api/v1/admin/skills/{id}
PATCH  /api/v1/admin/skills/{id}
DELETE /api/v1/admin/skills/{id}
POST   /api/v1/admin/skills/{id}/approve
POST   /api/v1/admin/skills/{id}/reject
GET    /api/v1/admin/skills/primitives/catalog
```

## 28.15 OAuth + integrazioni

```
GET  /api/v1/oauth/google/status
GET  /api/v1/oauth/google/authorize?scope_set=calendar:rw|gmail:ro
GET  /api/v1/oauth/google/callback     (Google → CARA)

GET    /api/v1/integrations
POST   /api/v1/integrations
DELETE /api/v1/integrations/{provider}
```

## 28.16 Email proposals

```
GET  /api/v1/proposals
POST /api/v1/proposals/{id}/accept
POST /api/v1/proposals/{id}/reject
```

## 28.17 Push

```
POST   /api/v1/push/subscribe
DELETE /api/v1/push/subscribe/{id}
GET    /api/v1/push/subscriptions
POST   /api/v1/push/test
```

## 28.18 Devices

```
POST /api/v1/devices/pair/start         (anon)
GET  /api/v1/devices/pair/status?code=  (anon)
POST /api/v1/devices/pair/finalize       (admin)
GET  /api/v1/devices                     (admin)
GET  /api/v1/devices/{id}                (admin)
PATCH /api/v1/devices/{id}               (admin)
DELETE /api/v1/devices/{id}              (admin)
POST /api/v1/devices/heartbeat           (device JWT)
```

## 28.19 Setup wizard

```
GET  /api/v1/setup/status               (anon)
POST /api/v1/setup/admin                (anon, single-shot)
POST /api/v1/setup/cert/regenerate      (admin)
POST /api/v1/setup/cert/skip
POST /api/v1/setup/family
POST /api/v1/setup/voice
POST /api/v1/setup/llm
POST /api/v1/setup/homeassistant/test
POST /api/v1/setup/homeassistant
POST /api/v1/setup/vapid/generate
POST /api/v1/setup/telegram
POST /api/v1/setup/integrations/complete
POST /api/v1/setup/google
POST /api/v1/setup/cloud/test
POST /api/v1/setup/cloud
POST /api/v1/setup/feature-flags
POST /api/v1/setup/complete
POST /api/v1/setup/reset
```

## 28.20 Admin

```
GET   /api/v1/admin/settings
PATCH /api/v1/admin/settings
GET   /api/v1/admin/audit?limit=&action=

GET   /api/v1/admin/memory/users
GET   /api/v1/admin/memory/{user_id}/facts
DELETE /api/v1/admin/memory/{user_id}/facts/{fact_id}
POST  /api/v1/admin/memory/{user_id}/purge

POST  /api/v1/admin/habits/detect
GET   /api/v1/admin/habits/candidates
POST  /api/v1/admin/habits/{id}/review

POST  /api/v1/admin/reflective/run

GET   /api/v1/admin/tool-metrics/stats
GET   /api/v1/admin/tool-metrics/top-failures
GET   /api/v1/admin/tool-metrics/recent

GET   /api/v1/admin/tts/overrides
PUT   /api/v1/admin/tts/overrides
PATCH /api/v1/admin/tts/overrides
DELETE /api/v1/admin/tts/overrides/{word}
POST  /api/v1/admin/tts/preview

GET   /api/v1/admin/proactivity/rules
POST  /api/v1/admin/proactivity/evaluate
GET   /api/v1/admin/proactivity/suggestions

GET   /api/v1/admin/diagnostics/health
POST  /api/v1/admin/diagnostics/self-test

POST  /api/v1/tools/metric             (frontend report tool-call)
GET   /api/v1/tools/error-classes
```

## 28.21 CDA

```
POST /api/v1/cda/discover
GET  /api/v1/cda/items
POST /api/v1/cda/feedback/started
POST /api/v1/cda/feedback/stopped
POST /api/v1/cda/feedback/regenerated
PATCH /api/v1/cda/items/{id}/active   (admin)
```

## 28.22 Eventi

```
GET /api/v1/events                     (filtri kind, since, user)
```

## 28.23 Total count

| Categoria | Endpoint count |
|---|---|
| Health | 5 |
| Auth | 6 |
| Chat | 5 |
| CRUD task/spesa/note | 11 |
| News/radio/weather | 5 |
| Voice/STT | 5 |
| Family + WS | 2 |
| Files | 5 |
| Memory | 7 |
| Wallet+widgets | 8 |
| Smart home | 6 |
| Budget+spese | 5 |
| Workflow | 4 |
| Skill admin | 8 |
| OAuth + integrazioni | 6 |
| Proposals | 3 |
| Push | 4 |
| Devices | 8 |
| Setup wizard | 18 |
| Admin | 21 |
| CDA | 6 |
| Events | 1 |
| **Totale** | **~149** |

## 28.24 Vedere lo schema completo

Per il dettaglio request/response di ogni endpoint, in development:

```
https://192.168.1.23:8455/api/docs           (Swagger UI)
https://192.168.1.23:8455/api/openapi.json   (raw OpenAPI 3)
```

Esempio import Postman:

```bash
curl -sk https://192.168.1.23:8455/api/openapi.json > cara-openapi.json
# Importa cara-openapi.json in Postman / Insomnia / Bruno
```

In produzione (`CARA_ENV=production`), Swagger è disabilitato per
sicurezza.

---

[← Cap 27 Riferimento admin_settings](27-admin-settings.md) · [README](README.md) · [Cap 29 Riferimento WebSocket →](29-websocket.md)
