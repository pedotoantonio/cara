# Cap 4 — Backend, moduli profondi

> *Sintesi 30 secondi.* Il backend è scritto in Python 3.11 con FastAPI.
> Vive in `backend/cara/`, organizzato in 16 sotto-pacchetti, ognuno con
> uno scopo preciso. Questo capitolo è la mappa: per ogni pacchetto
> spieghiamo cosa fa, dove vive il codice principale, e come usarlo.

I file pesanti (LLM, NPU, codice generativo) hanno il loro capitolo
dedicato (cap 6 AI/LLM, cap 7 voce). Qui ci concentriamo sui pacchetti
applicativi.

## 4.1 `cara.config` — Settings via Pydantic

**Cosa fa**: legge le variabili d'ambiente al boot e le espone come
oggetto `settings` tipizzato. Ogni modulo che ha bisogno di un valore
configurabile lo prende da qui.

**Perché esiste**: centralizzare la configurazione, validarla all'avvio
(così se manca qualcosa esce subito un errore chiaro), avere
auto-completamento nell'IDE.

**Come si usa**:

```python
from cara.config import settings

if settings.tts_enabled:
    await init_tts_service(voices_dir=settings.tts_voices_dir)
```

**Aggiungere un parametro nuovo**: edita `cara/config.py`, aggiungi
una `Field` nella classe `Settings`. Pydantic la legge dalla variabile
d'ambiente con lo stesso nome (uppercased). Esempio:

```python
class Settings(BaseSettings):
    new_feature_max_items: int = Field(default=50, ge=1, le=1000)
    # legge la variabile NEW_FEATURE_MAX_ITEMS dal .env
```

> **💡 Suggerimento** — preferisci sempre `admin_settings` (DB) per
> flag che l'admin deve poter cambiare a caldo senza riavviare. `config.py`
> è solo per parametri statici (URL DB, segreti, path filesystem).

## 4.2 `cara.store` — Database engine

**Cosa fa**: crea l'engine SQLAlchemy async, espone `Base` (la classe
da cui ereditano tutti i modelli ORM), fornisce `get_session()` come
dependency FastAPI.

**File principale**: `cara/store/db.py`.

**Pattern di uso negli endpoint**:

```python
from cara.store import get_session
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

@router.get("/things")
async def list_things(
    session: AsyncSession = Depends(get_session),
) -> list[Thing]:
    return (await session.execute(select(Thing))).scalars().all()
```

`get_session()` apre una sessione per richiesta, la committa
automaticamente al ritorno, la rollback automaticamente in caso di
eccezione. Questo è il **comportamento atteso ovunque** — niente
session manuali nel codice applicativo.

> **⚠️ Attenzione** — nei task asyncio fuori dal ciclo di richiesta
> (scheduler, ws subscriber) **non** puoi usare `Depends(get_session)`.
> Devi prendere il `sessionmaker` da `get_sessionmaker()` e gestire
> la sessione a mano con `async with sm() as session:`. Esempi nel
> file `cara/services/push_scheduler.py`.

## 4.3 `cara.models` — ORM SQLAlchemy

**Cosa fa**: 25+ classi che mappano le tabelle Postgres. Tutti
ereditano da `Base`. L'`__init__.py` importa tutti i modelli, così
basta `import cara.models` per registrare le tabelle su `Base.metadata`.

**Modelli principali**:

| File | Modelli |
|---|---|
| `user.py` | `User` (auth, role, is_admin) |
| `conversation.py` | `Conversation`, `Message` |
| `task.py` | `Task` (con due_date e reminded_at) |
| `shopping.py` | `ShoppingItem` |
| `note.py` | `Note` |
| `event.py` | `Event` (episodic — JSONB payload) |
| `tool_metric.py` | `ToolCallMetric` (funnel parser→exec) |
| `fact.py` | `Fact` (memoria semantica + embedding JSONB) |
| `device.py` | `Device` (multi-device pairing) |
| `device_permission.py` | `DevicePermission` (matrix per ruolo) |
| `skill.py` | `Skill` (Skill Factory JSON) |
| `widget_layout.py` | `WidgetLayout` (Wallet) |
| `workflow_trust.py` | `WorkflowTrust` (auto-confirm) |
| `budget.py` | `Budget`, `Expense` |
| `oauth_credentials.py` | `OAuthCredentials` (cifrato AES-GCM) |
| `calendar_event.py` | `CalendarEvent` (mirror Google) |
| `email_proposal.py` | `EmailProposal`, `EmailLearningSignal` |
| `audit_log.py` | `AuditLog` |
| `admin_setting.py` | `AdminSetting` (key-value JSONB) |

**Convenzione UUID vs Integer**: gli ID utente-visibili (Task, Note,
Conversation, Skill) sono UUID. Gli ID interni di apprendimento
(Event, ToolCallMetric, Fact, HabitCandidate) sono BIGSERIAL — milioni
di righe possibili, UUID sarebbe spreco di spazio.

**Aggiungere un modello**:

1. Crea il file `cara/models/foo.py` con la classe ORM.
2. Aggiungi l'import a `cara/models/__init__.py` (registra su `Base.metadata`).
3. Genera la migration: `docker exec cara-backend alembic revision --autogenerate -m "add foo"`.
4. Verifica il file generato in `backend/alembic/versions/`. Alembic non sempre indovina; spesso vuole un edit manuale (es. nullable, indici).
5. Applica: `docker exec cara-backend alembic upgrade head`.
6. Aggiungi un test in `tests/unit/test_foo.py` che usa la fixture `db_session` (in-memory SQLite).

## 4.4 `cara.api.v1` — Endpoint REST

**Cosa fa**: tutti gli endpoint HTTP sono qui. L'`__init__.py`
aggrega 35+ sub-router, ognuno per un dominio. Ogni endpoint ha:

- Path parametrizzato (`@router.get("/things/{id}")`)
- Body Pydantic (`async def create(body: ThingCreate, ...)`)
- Dependency injection (`session: AsyncSession = Depends(get_session)`)
- Autenticazione (`user: User = Depends(get_current_user)` o `_admin: User = Depends(require_admin)`)
- Tipo di risposta dichiarato (`-> ThingOut` o `response_model=ThingOut`)

**Convenzioni di scrittura**:

```python
# Buono
@router.post("/things", response_model=ThingOut, status_code=status.HTTP_201_CREATED)
async def create_thing(
    body: ThingCreate,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ThingOut:
    thing = await thing_svc.create(session, user_id=user.id, **body.model_dump())
    await session.commit()
    return ThingOut.model_validate(thing)

# Cattivo (logica DB nell'endpoint, niente schema risposta)
@router.post("/things")
async def create_thing(body: dict, session = Depends(get_session)):
    t = Thing(...)
    session.add(t)
    await session.commit()
    return {"id": t.id}
```

**Le 35+ route** sono elencate nel cap 28 (Riferimento API REST).

**Endpoint privati `_chat_*.py`**: non sono router. Sono helper
estratti da `chat.py` durante il refactor 0.2 (vedi commit
`9f63122 refactor(chat): Step 0.2 phase C`). Iniziano con underscore
per chiarezza.

## 4.5 `cara.api.deps` — Dipendenze FastAPI

**Cosa fa**: tre dependency principali usate ovunque.

```python
from cara.api.deps import get_session, get_current_user, require_admin

# get_session: apre sessione DB per la richiesta
# get_current_user: verifica JWT Bearer → ritorna User
# require_admin: come get_current_user MA fa raise 403 se !is_admin
```

`get_current_user` legge l'header `Authorization: Bearer <jwt>`, lo
decodifica con `jose`, carica l'utente da Postgres. Se manca il token
o è invalido → 401. Se il token è scaduto → 401 (il client deve fare
refresh).

**Aggiungere una nuova dependency**: aggiungila in `deps.py`. Non
duplicarne logiche fra endpoint.

## 4.6 `cara.services` — Logica di business

**Cosa fa**: tutto il "come si fa una cosa" che NON è layer HTTP. Gli
endpoint chiamano questi servizi, mai il contrario.

**Servizi principali**:

| File | A cosa serve |
|---|---|
| `auth.py` | Hash password (bcrypt), JWT issue/verify, authenticate() |
| `audit.py` | Scrivi entry in audit_log |
| `admin_settings.py` | DEFAULTS dict + get/set per i flag runtime |
| `conversations.py` | CRUD conversation + message persistence |
| `tasks.py` | CRUD task |
| `shopping.py`, `notes.py` | CRUD relativi |
| `intent_router.py` | Tier-1 deterministico (regex → intent kind) |
| `recipe_chain.py` | Tier-0.5 legacy ricetta → ingredienti |
| `quick_calc.py` | Math/date/time intercept (no LLM) |
| `extractive_summary.py` | TF-IDF top sentences |
| `it_date_parser.py` | "domani 15:00" → datetime |
| `response_cache.py` | Redis cache risposte chat |
| `weather.py` | Open-Meteo + WMO icon mapping |
| `budgets.py` | Budget CRUD + month_rollup |
| `devices.py` | Pairing flow (codice 6 cifre + Redis) |
| `env_writer.py` | Atomic .env mutation |
| `secrets.py` | AES-GCM per OAuth tokens |
| `push.py` + `push_scheduler.py` | VAPID send + scheduler tick |
| `family_bus.py` | Redis pub/sub WebSocket |
| `smarthome_events.py` | WS subscriber HA → episodic |
| `smarthome_permissions.py` | check_permission(user, entity, action) |
| `proactivity/engine.py` + `proactivity/rules.py` | Engine + 10 rules |
| `cloud_llm.py` | Hooks Anthropic (DEFERRED) |
| `diagnostics.py` | Self-test sistema |
| `integrations/calendar_sync.py` | Pull eventi da Google |
| `integrations/calendar_push.py` | Push eventi a Google |
| `integrations/gmail_scanner.py` | Scan Gmail → email proposals |
| `integrations/email_understanding.py` | NLU 3-livelli email |

**Pattern: tutti i servizi sono async** e accettano `session:
AsyncSession` come primo parametro (esplicito, non `Depends`). Questo
li rende facilmente unit-testabili con la fixture `db_session`
in-memory.

**Aggiungere un servizio**: crea `cara/services/foo.py`, scrivi
funzioni async pure. Niente classi se non servono — moduli con
funzioni top-level.

## 4.7 `cara.ai` — AI/LLM/embeddings

Vedi cap 6 (AI/LLM) per il dettaglio. Riassunto:

- `llm.py` — `LLMService` async-safe singleton, lock asyncio per
  serializzare le inferenze (un worker per volta sulla NPU)
- `_rkllm_bindings.py` — ctypes bindings a `librkllmrt.so`
- `kv_cache.py` — gestione file KV cache RKLLM (1 file per
  conversation)
- `embeddings.py` — MiniLM multilingual 384-d, lazy load + Redis cache
- `ner.py` — spaCy + 7 regex PII + family glossary
- `ocr.py` — Tesseract + OpenCV preprocessing
- `tts/` — Piper TTS engine + normalizzatore anglicismi YAML

## 4.8 `cara.cda` — Content Discovery Agent

Vedi cap 13 (CDA). Riassunto:

- Cerca su web (SearXNG / DuckDuckGo) → estrae con trafilatura → verifica
  → persiste in `cda_content_items`
- Discovery per tipo: article, audio_stream, podcast, video, image,
  document
- Rate limit Redis token bucket
- Maintenance batch (cleanup KB stale)

## 4.9 `cara.core` — Stato globale

**Cosa fa**: due singleton process-wide.

- **`bus.py`**: pub/sub interno **al backend** (non Redis). Eventi
  veloci da fan-out a tutti i consumer in process.
- **`state_machine.py`**: FSM `idle → listening → thinking → speaking
  → idle`. Mantiene lo stato attuale per il frontend (mostra
  l'avatar nel mood giusto).

```python
from cara.core import get_state_machine, LumoState, get_bus

sm = get_state_machine()
sm.transition(LumoState.THINKING)

bus = get_bus()
await bus.publish("chat.turn.completed", {"convo_id": "..."})
```

> **⚠️ Attenzione** — `bus.py` è SOLO in process. Per cross-process
> (frontend WS, multi-device) usa `cara.services.family_bus` (Redis
> pub/sub).

## 4.10 `cara.integrations` — Provider esterni

**Cosa fa**: wrapper a basso livello sui provider terzi. Niente
business logic, solo HTTP/SDK call e shape dei dati.

| File | Provider |
|---|---|
| `google_oauth.py` | OAuth 2.0 PKCE flow (authorize_url, exchange, refresh) |
| `google_calendar.py` | Calendar API (list, insert, patch, delete) |
| `google_gmail.py` | Gmail API **read-only** (4 livelli garantiti — vedi cap 16) |
| `telegram.py` | python-telegram-bot wrapper opt-in |

I file `services/integrations/*` sono il livello superiore: usano
questi e applicano logica.

## 4.11 `cara.learning` — Apprendimento

Vedi cap 8 (Memoria) e cap 11 (Proattività). Riassunto:

- `episodic.py` — scrivi/leggi `events` con `record_async` fire-and-forget
- `semantic.py` — `detect_facts(message)` (pattern regex IT) + `top_k_for_query`
- `tool_metrics.py` — funnel a 4 gate (parse → name → args → exec)
- `habits.py` — detector pattern ricorrenti (3-hour bucket)
- `reflective.py` — cluster miss (cosine) + cluster failure (group by error_class)

## 4.12 `cara.router` — Pipeline di routing

**Cosa fa**: astrazione `Pipeline` + `Stage` Protocol. Il chat layer
attualmente usa il loop `for handler in ROUTING_TIERS`, ma è già
sostituibile con `Pipeline.route(ctx)` (factory in
`api/v1/_chat_pipeline.py`).

Vedi cap 9 (Skill Factory) e cap 25.5 (estendere il routing).

## 4.13 `cara.skills` — Skill Factory

Vedi cap 9 (Skill Factory). Riassunto:

- `registry.py` — `@primitive` decorator, `_PRIMITIVES` dict
- `primitives.py` + `primitives_generic.py` — 7 primitive built-in
- `executor.py` — esecuzione lineare di un piano JSON (`{slot}` resolution)
- `dispatcher.py` — Tier-1 regex / Tier-2 cosine / Tier-3 LLM
- `author.py` — Cloud LLM authoring (Phase D, opt-in)

## 4.14 `cara.smarthome` — Smart home abstraction

Vedi cap 12 (Smart Home). Riassunto:

- `base.py` — `SmartHomeAdapter` Protocol + tipi canonical
- `homeassistant.py` — adapter REST per HA
- `ws_client.py` — WebSocket subscriber HA events
- `nlu.py` — 4-stage natural language → action+entity

## 4.15 `cara.widgets` — Wallet engine

Vedi cap 10 (Wallet). Riassunto:

- `base.py` — `Widget` Protocol, `WidgetRegistry` con isolation
- `catalog.py` — 7 widget core
- `catalog_extra.py` — 6 widget extra

## 4.16 `cara.workflows` — Workflow concreti

Vedi cap 14 (Workflow). Riassunto:

- `base.py` — Pattern `classify → extract → propose → execute`
- `receipt.py` — Scontrino → categorizzazione spese
- `bill.py` — Bolletta → reminder + expense
- `recipe.py` — URL/foto/text → ingredienti → spesa
- `auto_confirm.py` — Trust streak per (user, workflow, signature)

## 4.17 Convenzioni trasversali

**Errori**: gli endpoint sollevano `HTTPException(status_code, detail)`
per errori utente; i servizi sollevano eccezioni Python normali (`ValueError`,
`PermissionError`, custom). L'endpoint le trasforma in HTTPException.

**Logging**: sempre `structlog`, nome del modulo:

```python
import structlog
log = structlog.get_logger(__name__)

log.info("event.name", key=value, key2=value2)
```

Gli eventi hanno **nome puntato** (es. `chat.skill_run`,
`router.miss`, `setup.step.tls`) — pattern standard CARA.

**Import lazy** per moduli pesanti: `numpy`, `cv2`, `pytesseract`,
`trafilatura`, `transformers` vanno importati DENTRO le funzioni che
li usano, non al top del file. Il test in-memory non li carica così.

**Async ovunque**: niente `time.sleep()` (usa `asyncio.sleep`),
niente `requests` (usa `httpx`), niente `psycopg2` (asyncpg).

**Test**: ogni servizio + ogni endpoint ha almeno un test. Coverage
attuale: 641 unit + 160 smoke = 801 verdi.

---

[← Cap 3 Struttura repo](03-struttura-repo.md) · [README](README.md) · [Cap 5 Frontend deep-dive →](05-frontend-moduli.md)
