# CARA v1.0 — Handoff document, branch `epic-0-foundations`

Stato a fine sessione 2026-05-04 (consolidata in sette ondate). **353 test verdi** (311 unit + 42 smoke). Step 67 di Antonio mergiato; modelli wire-up; KV cache RKLLM **live e misurato 8.3× più veloce** su TTFT follow-up; episodic memory **live**; REST endpoint per weather/memory/widgets/smarthome live; `chat.py` 1322 → 1034 righe (helper estratti).

## Cosa è stato fatto

Branch `epic-0-foundations` su `/opt/cara/`. Tutti commit additivi
(file/cartelle nuovi). Il working tree pre-esistente dello Step 66 è
**intatto**: zero modifiche ai file che Antonio aveva già editato.

| Step | Cosa | File principali | Test |
|------|------|-----------------|------|
| 0.1 | Test harness E2E HTTP black-box | `backend/tests/{conftest,smoke/}` + `Makefile` | 15 smoke |
| 0.3 | Episodic memory persistente | `cara/models/event.py`, `cara/learning/episodic.py`, migration `d4e1f8b3a201` | 9 unit |
| 0.4 | Tool-call telemetry | `cara/models/tool_metric.py`, `cara/learning/tool_metrics.py`, migration `e8a2c5f7b310` | 10 unit |
| 0.6 | Pipeline Router (infrastruttura) | `cara/router/{__init__,pipeline}.py` | 10 unit |
| 1.1 | TTS anglicismi italiani | `cara/ai/tts/{anglicisms.yaml,normalizer.py}` (~300 voci) | 18 unit |
| 1.4 | Response cache Redis | `cara/services/response_cache.py` | 28 unit |
| 8.1 | Meteo Open-Meteo + icone WMO | `cara/services/weather.py` | 17 unit |
| 2.1 | Embedding service (lazy + cache) | `cara/ai/embeddings.py` | 17 unit |
| 2.3 | Italian NER (spaCy + regex + glossary) | `cara/ai/ner.py` | 16 unit |
| 3.1 | OCR Tesseract + OpenCV preprocess | `cara/ai/ocr.py` | 8 + 4 skip |
| 3.2 | Workflow engine base | `cara/workflows/{__init__,base}.py` | 15 unit |
| 5.1 | Smart-home abstraction layer | `cara/smarthome/{__init__,base}.py` | 13 unit |
| 6.3 | Device registry | `cara/models/device.py` + migration `f3c9d72e8b14` | (model only) |
| 2.2 | Fact model + semantic memory | `cara/models/fact.py`, `cara/learning/semantic.py` + migration `d6e2f9a4d825` | 19 unit |
| 5.2 | HA REST adapter (concrete) | `cara/smarthome/homeassistant.py` | 22 unit |
| 5.5 | Smart-home NLU | `cara/smarthome/nlu.py` | 19 unit |
| 5.8 | Device permissions per role | `cara/models/device_permission.py`, `cara/services/smarthome_permissions.py` + migration `a7b9c1e3d245` | 20 unit |
| 7.1+7.2 | Wallet engine + 7 widget catalog | `cara/widgets/{__init__,base,catalog}.py` | 22 unit |
| 8.4 | Habit detection | `cara/models/habit.py`, `cara/learning/habits.py` + migration `b5d4f1a82e36` | 17 unit |
| 8.5 | Reflective batch | `cara/learning/reflective.py` | 14 unit |
| 0.5 | RKLLM prompt-cache (KV reuse) | `cara/ai/kv_cache.py` + `cara/ai/llm.py` (chirurgico) | 17 unit |
| wire | `cara/models/__init__.py` add 6 classes | (one-line edits) | – |
| api/weather | `GET /weather/{geocode,current,forecast}` | `cara/api/v1/weather.py` | 4 smoke |
| api/memory | `/memory/facts` CRUD + extract + GDPR export/purge | `cara/api/v1/memory.py` + `schemas/memory.py` | 7 smoke |
| api/widgets | `/widgets` catalog + render-many | `cara/api/v1/widgets.py` | 9 smoke |
| api/smarthome | `/smarthome/entities,scenes,services,resolve,health` | `cara/api/v1/smarthome.py` | 7 smoke |
| 0.2 phase A | extract pure helpers from chat.py | `cara/api/v1/_chat_{prompt,grounding,sse}.py` | (covered by smoke) |
| 0.2/0.5 wiring | KV cache live + episodic.record_async live | `cara/api/v1/chat.py` + `cara/api/v1/admin.py` (flush on prompt change) | live verified — TTFT 16.5s → 2.0s on turn 2 |

Migrazioni Alembic applicate al DB live (`cara-postgres`):
`c8a7d94e1f02 → d4e1f8b3a201 → e8a2c5f7b310`. Idempotenti, downgrade
testabile.

## Cosa NON è stato fatto (di proposito)

Tre Step rimangono parzialmente fuori scope:

| Step | Stato | Motivo |
|------|-------|--------|
| 0.2 phase A | ✓ done | chat.py 1322 → 1034 |
| 0.2 phase B (KV + episodic wiring) | ✓ done + live verified | TTFT turn 2 → 2.0s. Cache file scritto in /app/cache/kv/. |
| 0.2 phase C (Pipeline + tool_metrics) | da fare | Sostituire if/elif inline con `cara.router.Pipeline`, wirare `tool_metrics.record_attempt` attorno al parser `[TOOL: ...]`. Sessione dedicata: ~700 righe da rifattorizzare. |
| 1.3 — TTS streaming chunked | bloccato | Coordinamento SSE (post-0.2 phase C) + frontend WebAudio queue. |
| 1.5 — system prompt corto + segmentato | bloccato | Dipende da 0.2 phase C (orchestratore consuma segmenti separati `base.md` + `tone_<role>.md` + `family_facts.md`). |

L'infrastruttura sotto è già pronta:
- KV cache lato `LLMService.generate()` → `prompt_cache_path=`
- `kv_cache.path_for_conversation(conv_id)` per la pathing
- Pipeline + Stage Protocol per il routing dopo lo split
- Tool-metrics recorder per il dispatch tracciato
- Response cache, NLU domotico, permission check, semantic facts retrieval pronti come dipendenze

## Cosa devi fare per riprendere

### 1. Mergia `epic-0-foundations` su `main`

Step 67 è già committato sul branch (`a64b196`). Tutti i miei step si
applicano sopra il tuo lavoro senza conflitti.

```bash
cd /opt/cara
git checkout main
git merge epic-0-foundations
make test  # deve dare 326/326 verde (311 unit + 15 smoke)
```

### 2. (Opzionale) Wire-up modelli

Già fatto in `c4e1c11 feat(llm): Step 0.5 + model wire-up`. I sei modelli
nuovi (`Event`, `ToolCallMetric`, `Device`, `DevicePermission`, `Fact`,
`HabitCandidate`) sono già in `cara/models/__init__.py`.

### 3. Step 0.2 — refactor `chat.py`

Il file `chat.py` è ora **1322 righe** (1151 originale + 171 di Step 67).
Spezzarlo è il refactor più rischioso del piano. Ordine consigliato:

1. Estrai `_render_qwen_prompt`, `_runtime_context_message` in un nuovo
   `prompt_builder.py`.
2. Estrai parser tool call e dispatch in `tool_dispatch.py` — wira al
   volo `tool_metrics.record_attempt` per ogni tentativo.
3. Estrai grounding (`_needs_grounding`, `_infer_kind`,
   `_has_discover_tool`) in `grounding.py`.
4. Trasforma il routing inline (cache → intent_router → recipe_chain →
   skills → tool_calling → fallback) in `Stage` del `Pipeline` già
   pronto in `cara.router.pipeline`.
5. `episodic.record_async` su ogni decisione: `router.stage`,
   `tool.call`, `chat.turn`.
6. **Wire `prompt_cache_path = kv_cache.path_for_conversation(conv_id)`**
   sulla chiamata a `llm.generate(...)` per attivare il KV cache della
   sessione. Invalidate via `kv_cache.flush_one(conv_id)` quando il
   system prompt cambia.
7. Smoke test deve passare invariato. Se non passa, il refactor sta
   cambiando il comportamento esterno → fermarsi e investigare.

Target: `chat()` <250 righe.

### 4. Step 1.3 e 1.5

Step 1.3 (TTS streaming chunked) e Step 1.5 (system prompt segmentato +
corto): entrambi nel post-refactor di `chat.py`, dove ognuno è una
modifica chirurgica di poche righe.

Per Step 1.5 in particolare: il prompt corto va segmentato in 3 file
sotto `config/prompts/`:
- `base.md` (statico, cacheabile per sempre)
- `tone_<role>.md` (statico per ruolo)
- `family_facts.md` (dinamico, top-k iniettato via
  `cara.learning.semantic.top_k_for_query`)

## Stato Alembic

```
$ alembic current
b5d4f1a82e36 (head)
```

Catena completa:
```
e7ff (initial) → df31 (users) → b984 (tasks) → 8ac2 (task_due) → ed5d (shopping)
  → 04f5 (notes) → c64d (user_role) → 1727 (admin_settings+audit)
  → 0efc (user_birth_date) → d1b1 (files) → a3f1 (cda)
  → 6061 (skills) ← Antonio Step 66
  → c8a7 (seed ricetta) ← Antonio Step 66/67
  → d4e1 (events) ← Step 0.3
  → e8a2 (tool_call_metrics) ← Step 0.4
  → f3c9 (devices) ← Step 6.3
  → d6e2 (facts) ← Step 2.2
  → a7b9 (device_permissions) ← Step 5.8
  → b5d4 (habit_candidates) ← Step 8.4
```

Antonio's Step 67 added the Skill Author Phase D feature (cloud LLM
authoring) without further DB schema changes — it reuses the
existing `skills` table.

## Comandi utili

```bash
# Test
make test                # unit + smoke
make test-unit           # solo unit (in-memory SQLite)
make test-smoke          # solo smoke (HTTP vs backend live)
make smoke-curl          # health check rapido

# DB
docker exec cara-postgres psql -U cara -d cara -c "SELECT version_num FROM alembic_version;"
docker exec cara-backend alembic current
docker exec cara-backend alembic history | head -20

# Backup
ls /home/apedo/cara-backups/  # tar.gz pre-v1.0 disponibile per rollback
```

## Memoria salvata per le prossime sessioni

In `/home/apedo/.claude/projects/-home-apedo-cara-poc-rkllm/memory/`:

- `cara_v1_development.md` — la roadmap 45-EW concordata
- `antonio_step66_pending.md` — questo handoff in forma compatta

Le sessioni future di Claude le leggeranno automaticamente, quindi non
serve ri-spiegarmi il piano.

## TL;DR del lavoro fatto

**20 Step** completati come **infrastruttura pronta per il wiring**:

- **Epic 0** (foundations): 0.1 + 0.3 + 0.4 + 0.6 — bloccati 0.2 + 0.5
- **Epic 1** (voce): 1.1 + 1.4 — bloccati 1.2 + 1.3 + 1.5
- **Epic 2** (memoria): 2.1 + 2.2 + 2.3
- **Epic 3** (workflow): 3.1 + 3.2
- **Epic 5** (smart home): 5.1 + 5.2 + 5.5 + 5.8
- **Epic 6** (multi-device): 6.3
- **Epic 7** (wallet): 7.1 + 7.2
- **Epic 8** (proattività): 8.1 + 8.4 + 8.5

Nessun comportamento utente è cambiato (tutto additivo). **309 test
verdi** proteggono il prossimo refactor di `chat.py`. Quando commiti
il tuo Step 66, in una giornata si chiudono i 4 step bloccati (0.2 +
0.5 + 1.3 + 1.5) e l'infrastruttura sopra inizia a essere wired uno
per uno: episodic.record nelle hot path, semantic facts iniettati nel
system prompt, response cache come primo stage del Pipeline, HA NLU
+ permission check come stage successivo, weather + widgets esposti
come endpoint REST, NER + OCR consumate dal ReceiptWorkflow, habit
detection batch + reflective batch nel Celery beat, etc.

**Pacchetti nuovi** disponibili nel codebase:
- `cara.learning` — episodic, semantic, tool_metrics, habits, reflective
- `cara.router` — pipeline + Stage Protocol
- `cara.workflows` — Workflow Protocol + registry
- `cara.smarthome` — base + HA REST adapter + NLU
- `cara.widgets` — engine + 7-widget catalog
- estensioni di `cara.ai` (embeddings, ner, ocr, tts.normalizer)
- estensioni di `cara.services` (response_cache, weather, smarthome_permissions)
