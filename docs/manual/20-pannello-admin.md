# Cap 20 — Pannello admin

> *Sintesi 30 secondi.* `/admin` è la dashboard amministratore: 14+
> feature flag, system prompt runtime editor, voce TTS config, audit
> log viewer, link rapidi alle 6 sezioni admin (Skills, Memoria, Smart
> Home, Proattività, Devices, Diagnostics).

## 20.1 Layout `/admin`

**File**: `frontend/src/routes/AdminPage.tsx`.

L'AdminPage protegge sé stessa: `useEffect(() => { if
(!user.is_admin) navigate('/chat') })`. Le sub-route ereditano la
protezione.

```
+----------------------------------------+
| Pannello amministratore                 |
| Configurazione AI, integrazioni, audit |
+----------------------------------------+
| [Skill Factory →] [Memoria →] [Smart   |
|  Home →] [Proattività →] [Dispositivi →]|
|  [Diagnostica →]                        |
+----------------------------------------+
| Funzionalità (toggle)                   |
| ☑ Internet abilitato                    |
| ☐ News                                  |
| ☐ Radio                                 |
| ☑ CDA                                   |
| ☐ Cloud LLM                             |
| ... 14 flag totali                      |
+----------------------------------------+
| AI behaviour                            |
|   System prompt: [textarea]              |
|   Max new tokens: [slider]               |
|   Tone preset: [dropdown]                |
|   Validation: [toggle]                   |
|   Cognitive mode: [toggle]               |
+----------------------------------------+
| Voce (TTS)                              |
|   Voce: [dropdown Piper voices]          |
|   Rate / Pitch / Volume: [sliders]       |
+----------------------------------------+
| Audit log (tab)                          |
|   filtra per action                       |
|   ultime 100 entry                        |
+----------------------------------------+
| Sezione tools (debug)                    |
|   Diagnosi sistema → /admin/diagnostics  |
|   Face Lab → /face-lab                   |
+----------------------------------------+
```

## 20.2 Feature flags — 14 toggle

`FEATURE_FLAGS` in `AdminPage.tsx`:

| Key | Cosa fa |
|---|---|
| `internet_enabled` | Master switch per news/radio/web |
| `news_enabled` | Aggregator news (richiede internet) |
| `video_enabled` | Discovery video (richiede internet) |
| `radio_enabled` | Discovery radio internet |
| `habit_learning_enabled` | Detector pattern ricorrenti |
| `proactive_suggestions_enabled` | Engine proattività |
| `telegram_bot_enabled` | Bot wrapper |
| `facial_recognition_enabled` | Frigate-faces integration |
| `voice_recognition_enabled` | Web Speech API |
| `smart_home_enabled` | HA adapter |
| `push_notifications_enabled` | Push scheduler |
| `cloud_llm_enabled` | Anthropic Haiku (DEFERRED) |
| `validation_enabled` | LLM validation pipeline (richiede 3B+) |
| `cognitive_mode` | Modalità ragionamento approfondito |

I toggle scrivono direttamente in `admin_settings` via `PATCH /admin/settings`.

## 20.3 System prompt + AI tuning

3 textarea + 2 slider:

```
- llm_system_prompt          (override del prompt di base)
- llm_validation_prompt      (per il validator pipeline)
- llm_cognitive_prompt       (per cognitive_mode)
- llm_max_new_tokens         (slider 64-1024)
- llm_validation_max_tokens  (slider)
```

Su `PATCH /admin/settings` con chiave in `("llm_system_prompt", "tone")`,
il backend chiama `kv_cache.flush_all()` per invalidare il prefix
cached.

## 20.4 Voce TTS

Dropdown voci Piper (auto-detected dal `data/tts/piper/voices/`) +
slider rate/pitch/volume. Anteprima audio inline.

```
voice_name:    "it_IT-paola-medium"
voice_rate:    1.0       (0.5-2.0)
voice_pitch:   1.0       (0-2)
voice_volume:  1.0       (0-1)
```

Scrivono in `admin_settings`. Il TTS service li legge runtime per
ogni `synthesize` call.

## 20.5 Audit log viewer

Tab "Audit" in `AdminPage`. Tabella con:

```
[timestamp] [actor] [action] [target] [ip] [detail]
```

Filtri:
- Per `action` (text contains)
- Per actor email
- Last N (100 default)

Endpoint `GET /admin/audit?limit=100&action=skill.*`.

## 20.6 Sub-pages admin

### `/admin/skills` (cap 9.7)

Skill Factory: list skill (pending/active/disabled), edit JSON, approve,
disable, delete. Catalogo primitive in fondo.

### `/admin/memory` (cap 8.4)

Roster utenti famiglia con counts fact (totali/attivi). Click utente →
lista fact → soft-delete o purge totale. Audit log scrive azione.

### `/admin/smart-home` (cap 12.9)

Entities, scenes, NLU debug, aliases, events tail.

### `/admin/proactivity` (cap 11.4)

Lista rules, toggle on/off, "Esegui ora", lista suggestion recenti.

### `/admin/devices` (cap 15.5)

Lista device paired. Rename, change surface, deauth.

### `/admin/setup` (cap 18.1)

Riapri setup wizard per riconfigurare.

### `/admin/diagnostics` (cap 21)

Diagnostic suite: container health, NPU usage, log tail, self-test.

## 20.7 Endpoints admin REST

**File principali**: `cara/api/v1/admin.py`, `admin_learning.py`,
`admin_tts.py`, `diagnostics.py`.

| Endpoint | Cosa fa |
|---|---|
| `GET /admin/settings` | Tutti i flag con valori correnti |
| `PATCH /admin/settings` | Aggiorna alcuni |
| `GET /admin/audit?limit=&action=` | Log entries |
| `GET /admin/skills` | Lista skill (cap 9) |
| `POST /admin/skills/author` | Genera via cloud LLM |
| `PATCH /admin/skills/{id}` | Edit |
| `POST /admin/skills/{id}/approve` | active |
| `POST /admin/skills/{id}/reject` | disabled |
| `DELETE /admin/skills/{id}` | rimuovi |
| `GET /admin/memory/users` | Roster con counts |
| `GET /admin/memory/{user}/facts` | Fact di un utente |
| `DELETE /admin/memory/{user}/facts/{id}` | Soft-delete |
| `POST /admin/memory/{user}/purge` | Hard-delete tutti |
| `POST /admin/habits/detect` | Run detector |
| `GET /admin/habits/candidates` | Lista candidate |
| `POST /admin/habits/{id}/review` | accept/reject/dismiss |
| `POST /admin/reflective/run` | Cluster batch |
| `GET /admin/tool-metrics/stats` | Funnel parser→exec |
| `GET /admin/tool-metrics/top-failures` | Group by error_class |
| `GET /admin/tool-metrics/recent` | Ultimi failure |
| `GET /admin/tts/overrides` | Anglicismi user override |
| `PUT /admin/tts/overrides` | Replace tutto |
| `PATCH /admin/tts/overrides` | Merge |
| `DELETE /admin/tts/overrides/{word}` | Remove single |
| `POST /admin/tts/preview` | Dry-run normalize |
| `GET /admin/diagnostics/health` | Status sistema |
| `POST /admin/diagnostics/self-test` | Run check completo |

## 20.8 KV cache flush — quando

Il backend automaticamente flush la KV cache quando:

- `llm_system_prompt` cambia (prefix diverso)
- `tone` preset cambia
- `tts_user_overrides` cambia (no — non tocca il prompt LLM)

Manualmente l'admin può chiamare `POST /admin/diagnostics/kv-cache/flush`
(futuro endpoint).

## 20.9 Errori comuni

| Sintomo | Causa | Risoluzione |
|---|---|---|
| `PATCH /admin/settings` 400 | Chiave non in DEFAULTS | Aggiungi a `cara/services/admin_settings.py:DEFAULTS` |
| Settings non si applicano | Backend cached vecchi | Restart backend (alcuni settings sono letti al boot) |
| Audit log vuoto | Filtro action sbagliato | Rimuovi filtro action |
| `flush_all()` non funziona | KV cache file system non scrivibile | Verifica `/app/cache/kv/` esiste con permessi backend |

---

[← Cap 19 Sicurezza](19-sicurezza.md) · [README](README.md) · [Cap 21 Diagnostica e debug →](21-diagnostica-debug.md)
