# Cap 3 — Struttura del repository

> *Sintesi 30 secondi.* CARA è un monorepo con backend Python in
> `backend/`, frontend React in `frontend/`, configurazione Docker in
> root, e documentazione + script in `docs/` e `scripts/`. Questo
> capitolo è la mappa: dove vive cosa, e perché è organizzato così.

## 3.1 Vista dall'alto

```
/opt/cara/
├── README.md              # Quick-start per il primo lettore
├── CHANGELOG.md           # Changelog versioni v1.0.0+
├── LICENSE                # MIT
├── NOTICE                 # Attribuzioni open-source
├── Makefile               # Tutti i comandi quotidiani
├── docker-compose.yml     # Definizione 6 container CARA
├── .env                   # Configurazione runtime (gitignored)
├── .gitignore
│
├── backend/               # Backend Python (FastAPI)
│   ├── Dockerfile
│   ├── pyproject.toml     # Dipendenze + linter config
│   ├── alembic.ini
│   ├── alembic/           # Migration database
│   │   └── versions/
│   ├── cara/              # Codice applicativo
│   └── tests/             # Test unit + smoke
│
├── frontend/              # Frontend React (Vite)
│   ├── Dockerfile
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── nginx.conf         # Configurazione nginx interna del container
│   ├── public/            # Asset serviti staticamente
│   ├── src/               # Codice React
│   └── e2e/               # Test Playwright
│
├── data/                  # Persistenza host bind-mounted nei container
│   ├── postgres/          # Volume Postgres
│   ├── redis/             # Volume Redis
│   ├── minio/             # Volume MinIO
│   ├── chroma/            # Volume ChromaDB
│   ├── models/            # Modelli LLM (.rkllm)
│   ├── tts/               # Voci Piper (.onnx)
│   ├── uploads/           # Upload utente (foto, doc)
│   └── whisper-cache/     # Cache HuggingFace per Whisper
│
├── config/                # Configurazioni statiche (prompt template, ...)
├── build/                 # Artifact di build (TWA APK, ...)
├── backups/               # Backup Postgres giornalieri
│
├── docs/                  # Documentazione
│   ├── manual/            # Questo manuale
│   ├── HANDOFF-v1.0-epic-0-1.md
│   ├── MANUALE-FAMIGLIA.md
│   ├── MANUALE-ADMIN.md
│   ├── LORA-FINE-TUNE-PIPELINE.md
│   └── *-prompt.md        # Prompt di consegna per agenti AI
│
└── scripts/               # Script di manutenzione
    ├── backup-postgres.sh
    ├── cleanup-kv-cache.sh
    ├── export_lora_dataset.py
    ├── lora-train-runpod.sh
    └── systemd/           # Unit file (vuoto al momento)
```

I dati persistenti sono in `data/`. I container Docker bind-mountano
queste directory dentro di loro (`/var/lib/postgresql/data` → `data/postgres/`).
Questo permette backup banali (basta tar la directory) e portabilità
(sposti tutto su un altro host e riparte).

## 3.2 Backend: cosa c'è dentro `backend/cara/`

Questo è il cuore del codice Python. Ogni sotto-cartella è un dominio
funzionale. La regola: **una cartella = un'idea**.

```
backend/cara/
├── __init__.py            # Versione (__version__ = "0.1.0")
├── main.py                # Entrypoint FastAPI + lifespan
├── config.py              # Settings via Pydantic
├── bootstrap.py           # CLI: create-admin, reset-setup, ecc.
│
├── ai/                    # Modelli AI: LLM, embeddings, NER, OCR, TTS
│   ├── _rkllm_bindings.py # ctypes bindings a librkllmrt.so
│   ├── llm.py             # LLMService async-safe singleton
│   ├── kv_cache.py        # Gestione KV cache RKLLM
│   ├── embeddings.py      # MiniLM multilingual + cache Redis
│   ├── ner.py             # spaCy + regex + glossary IT
│   ├── ocr.py             # Tesseract + OpenCV
│   └── tts/               # Piper TTS engine + normalizzatore anglicismi
│
├── api/                   # Layer HTTP
│   ├── deps.py            # Dipendenze FastAPI (auth, get_session)
│   └── v1/                # API versione 1 (router prefisso /api/v1)
│       ├── __init__.py    # Aggregatore di tutti i sub-router
│       ├── _chat_*.py     # Helper privati di chat.py (refactor 0.2)
│       ├── chat.py        # POST /chat (SSE streaming)
│       ├── auth.py        # /auth/{login,register,refresh,me,...}
│       ├── tasks.py
│       ├── shopping.py
│       ├── notes.py
│       ├── conversations.py
│       ├── files.py
│       ├── voice.py
│       ├── asr.py
│       ├── memory.py      # /memory/facts CRUD + GDPR
│       ├── widgets.py     # Wallet engine HTTP wrapper
│       ├── wallet.py      # Layout persistence
│       ├── smarthome.py
│       ├── budgets.py
│       ├── workflows.py   # Receipt/Bill/Recipe execution
│       ├── proposals.py   # Email→task proposals
│       ├── proactivity.py
│       ├── push.py        # VAPID web push
│       ├── family.py      # who-is-home
│       ├── family_ws.py   # WebSocket bus
│       ├── integrations.py # Google connect/disconnect
│       ├── oauth.py       # /oauth/google/{authorize,callback}
│       ├── devices.py     # Multi-device pairing
│       ├── setup.py       # Setup wizard (cap 18)
│       ├── admin.py       # Admin panel (settings, audit, skills CRUD)
│       ├── admin_learning.py # Habits, reflective, tool-metrics
│       ├── admin_tts.py
│       ├── diagnostics.py
│       ├── events.py
│       ├── tools.py       # Tool-call telemetry endpoint
│       ├── news.py
│       ├── radio.py
│       ├── weather.py
│       ├── cda.py         # Content Discovery
│       └── device_aliases.py
│
├── auth/                  # Servizi auth (helper, non endpoint)
│
├── cda/                   # Content Discovery Agent
│   ├── __init__.py        # Public API: discover()
│   ├── base.py            # Tipi: Discovery, SearchHit, ContentType
│   ├── orchestrator.py    # Coordinatore search + verify + dedupe
│   ├── search/            # Provider di ricerca
│   │   ├── base.py
│   │   ├── searxng.py
│   │   ├── ddg.py
│   │   └── chain.py
│   ├── discovery/         # Estrattori per tipo
│   │   ├── article.py     # trafilatura + regex fallback
│   │   ├── audio_stream.py
│   │   ├── document.py
│   │   ├── image.py
│   │   ├── podcast.py
│   │   └── video.py
│   ├── verification/      # Health check + dedupe
│   │   ├── url_validator.py
│   │   └── stream_validator.py
│   ├── memory/            # Knowledge base persistente
│   │   ├── content_kb.py
│   │   └── user_preferences.py
│   ├── maintenance.py     # Job di pulizia KB
│   └── rate_limit.py      # Token bucket via Redis
│
├── core/                  # Stato globale: bus + state machine
│   ├── bus.py             # Pub/sub interno backend
│   └── state_machine.py   # FSM idle → listening → thinking → ...
│
├── integrations/          # Provider esterni
│   ├── google_oauth.py    # Token exchange + refresh
│   ├── google_calendar.py # CRUD eventi (read + write)
│   ├── google_gmail.py    # Read-only Gmail (4 livelli garantiti)
│   └── telegram.py        # Bot wrapper opt-in
│
├── learning/              # Memoria + apprendimento
│   ├── episodic.py        # events table writer/reader
│   ├── semantic.py        # facts extraction + retrieval
│   ├── tool_metrics.py    # Funnel parser → name → args → exec
│   ├── habits.py          # Detector pattern ricorrenti
│   └── reflective.py      # Cluster miss + failure (batch settimanale)
│
├── models/                # ORM SQLAlchemy
│   ├── __init__.py        # Importa tutti i modelli (registra Base.metadata)
│   ├── user.py
│   ├── conversation.py    # Conversation + Message
│   ├── task.py
│   ├── shopping.py
│   ├── note.py
│   ├── file.py
│   ├── event.py           # Episodic events
│   ├── tool_metric.py     # Tool-call funnel
│   ├── fact.py            # Semantic facts (con embedding JSONB)
│   ├── device.py          # Multi-device
│   ├── device_permission.py
│   ├── device_alias.py
│   ├── habit.py           # HabitCandidate
│   ├── skill.py           # Skill JSON
│   ├── widget_layout.py   # Wallet
│   ├── workflow_trust.py  # Auto-confirm streak
│   ├── budget.py          # Budget + Expense
│   ├── push_subscription.py
│   ├── oauth_credentials.py # Google OAuth tokens (cifrati)
│   ├── calendar_event.py  # Mirror Google Calendar
│   ├── email_proposal.py  # Email→task proposals
│   ├── audit_log.py
│   └── admin_setting.py
│
├── router/                # Pipeline di routing chat
│   ├── __init__.py
│   └── pipeline.py        # Stage Protocol + Pipeline class
│
├── schemas/               # Pydantic schemas (request/response)
│   ├── chat.py
│   ├── memory.py
│   └── ...
│
├── services/              # Logica di business
│   ├── auth.py            # JWT + password hashing
│   ├── audit.py           # Audit log writer
│   ├── admin_settings.py  # DEFAULTS + get/set
│   ├── conversations.py
│   ├── tasks.py
│   ├── shopping.py
│   ├── notes.py
│   ├── intent_router.py   # Tier-1 router deterministico
│   ├── recipe_chain.py    # Tier-0.5 legacy ricetta
│   ├── quick_calc.py      # Math/date/time intercept
│   ├── extractive_summary.py # Tf-idf top sentences
│   ├── it_date_parser.py  # "domani 15:00" → datetime
│   ├── response_cache.py  # Redis cache per chat
│   ├── weather.py         # Open-Meteo
│   ├── budgets.py
│   ├── devices.py         # Pairing service
│   ├── env_writer.py      # Atomic .env mutation
│   ├── secrets.py         # AES-GCM per OAuth tokens
│   ├── push.py            # VAPID send
│   ├── push_scheduler.py  # Tick reminder
│   ├── family_bus.py      # Redis pub/sub
│   ├── smarthome_events.py # WS subscriber HA
│   ├── smarthome_permissions.py # Role matrix
│   ├── device_aliases.py
│   ├── extractive_summary.py
│   ├── proactivity/       # Engine + rules
│   │   ├── engine.py
│   │   └── rules.py       # 10 rules concrete
│   ├── proactivity_scheduler.py
│   ├── cloud_llm.py       # Hooks DEFERRED
│   ├── diagnostics.py
│   └── integrations/      # Scheduler integrazioni
│       ├── calendar_sync.py
│       ├── calendar_push.py
│       ├── gmail_scanner.py
│       └── email_understanding.py
│
├── skills/                # Skill Factory v0.7
│   ├── __init__.py
│   ├── registry.py        # @primitive decorator + registry
│   ├── primitives.py      # Primitive built-in (3)
│   ├── primitives_generic.py # Phase B (4 nuove)
│   ├── executor.py        # Esecuzione step lineare
│   ├── dispatcher.py      # Tier-1/2/3 match
│   └── author.py          # Cloud LLM authoring (Phase D)
│
├── smarthome/             # Smart home abstraction
│   ├── __init__.py
│   ├── base.py            # Protocol + types canonical
│   ├── homeassistant.py   # HA REST adapter
│   ├── ws_client.py       # HA WebSocket client
│   └── nlu.py             # 4-stage smart-home NLU
│
├── store/                 # Database engine
│   └── db.py              # Async engine + sessionmaker + Base
│
├── tasks/                 # Celery tasks (poco usato)
│
├── utils/                 # Utility generici
│
├── widgets/               # Wallet engine
│   ├── __init__.py
│   ├── base.py            # Widget Protocol + Registry
│   ├── catalog.py         # 7 widget core
│   └── catalog_extra.py   # 6 widget extra
│
└── workflows/             # Workflow concreti
    ├── __init__.py
    ├── base.py            # Workflow Protocol + types
    ├── receipt.py         # ReceiptWorkflow
    ├── bill.py
    ├── recipe.py
    └── auto_confirm.py    # Trust streak
```

Ogni file Python segue la stessa struttura interna:

```python
"""Modulo X — descrizione di una riga.

Spiegazione di 3-5 righe del cosa fa, perché esiste, quali sono le
scelte di design importanti.
"""

from __future__ import annotations
import ...

# Costanti pubbliche

# Classi / dataclass

# Funzioni pubbliche

# Funzioni private (prefisso _)
```

## 3.3 Frontend: cosa c'è dentro `frontend/src/`

```
frontend/src/
├── App.tsx                # Entry point: routing, auth gate
├── main.tsx               # ReactDOM.createRoot
├── index.css              # Tailwind directives + global CSS
├── vite-env.d.ts          # Ambient types per __APP_VERSION__ ecc.
├── sw.ts                  # Service worker (Workbox custom)
│
├── api/                   # Client HTTP per ogni dominio
│   ├── auth.ts            # login, register, refresh, fetchMe
│   ├── chat.ts            # SSE stream
│   ├── tasks.ts
│   ├── memory.ts
│   ├── adminMemory.ts
│   ├── adminSkills.ts
│   ├── proactivity.ts
│   ├── workflows.ts
│   ├── widgets.ts
│   ├── wallet.ts
│   ├── smarthome.ts
│   ├── integrations.ts
│   ├── push.ts
│   ├── devices.ts
│   ├── setup.ts
│   ├── voice.ts
│   ├── admin.ts
│   └── ...
│
├── components/            # Componenti riutilizzabili
│   ├── AppShell.tsx       # Layout principale (nav + outlet)
│   ├── Login.tsx
│   ├── Chat.tsx
│   ├── MessageBubble.tsx
│   ├── LiveCaption.tsx
│   ├── WelcomeScreen.tsx
│   ├── InstallPwaPrompt.tsx
│   ├── WorkflowPreview.tsx
│   └── widgets/
│       └── WidgetCard.tsx
│
├── design/                # Design system
│   ├── index.ts           # Re-export tutto
│   ├── theme.tsx          # ThemeProvider (day/night)
│   ├── tokens.ts          # Colori, spacing, font
│   ├── components/        # Primitive UI
│   │   ├── Button.tsx
│   │   ├── Card.tsx
│   │   ├── Input.tsx
│   │   ├── Toast.tsx
│   │   ├── BottomSheet.tsx
│   │   ├── Badge.tsx
│   │   ├── IconButton.tsx
│   │   └── cn.ts          # Utility per className
│   └── icons/
│       └── index.tsx      # 29 icone SVG inline
│
├── hooks/                 # React hooks custom
│
├── i18n/                  # Stringhe (poco usato — UI è italian-first)
│
├── lib/                   # Utility generici
│   ├── userPrefs.ts       # localStorage tipizzato
│   ├── sounds.ts          # Audio sintetico
│   ├── speech.ts          # Web Speech wrapper
│   ├── piperTts.ts        # Piper voice list
│   ├── streamingAudio.ts  # WebAudio queue per TTS chunks
│   ├── voiceConversation.ts # FSM voce + STT + wake word
│   ├── familySync.ts      # WebSocket subscriber
│   ├── push.ts            # VAPID subscribe
│   └── offlineQueue.ts    # IDB queue per replay POST
│
├── routes/                # Pagine (1 file = 1 route)
│   ├── HomePage.tsx
│   ├── ChatPage.tsx
│   ├── TasksPage.tsx
│   ├── ShoppingPage.tsx
│   ├── NotesPage.tsx
│   ├── NewsPage.tsx
│   ├── RadioPage.tsx
│   ├── DiscoveriesPage.tsx
│   ├── WalletPage.tsx
│   ├── SettingsPage.tsx
│   ├── MemoryPage.tsx
│   ├── IntegrationsPage.tsx
│   ├── ProposalsPage.tsx
│   ├── PairPage.tsx
│   ├── SetupPage.tsx
│   ├── FaceLabPage.tsx
│   ├── AdminPage.tsx
│   ├── AdminMemoryPage.tsx
│   ├── AdminSkillsPage.tsx
│   ├── AdminSmartHomePage.tsx
│   ├── AdminProactivityPage.tsx
│   ├── AdminDevicesPage.tsx
│   └── DiagnosticsPage.tsx
│
├── stores/                # State management (poco usato — preferiamo context)
│
└── types/                 # Type definitions condivise
```

I componenti seguono la convenzione **PascalCase**, i file di
utilità **camelCase**. Le pagine sono in `routes/` con suffisso `Page`.

## 3.4 Convenzioni di codice

### Backend Python

- **Type hints** ovunque, mode strict per Pyright/mypy.
- **`from __future__ import annotations`** in cima a ogni file (lazy
  evaluation degli annotation).
- **Async-first**: tutti i database calls, HTTP esterni, file I/O sono
  `async def`.
- **`structlog`** per logging strutturato. Mai `print()`. Mai `logging.info`
  diretto. Sempre `log = structlog.get_logger(__name__)` in cima.
- **Pydantic v2** per request/response schemas.
- **SQLAlchemy 2.x** stile dichiarativo con `Mapped[T]` e
  `mapped_column()`.
- **Testabilità**: niente import top-level pesanti che caricano modelli.
  Lazy load dove possibile.

> **💡 Suggerimento** — se vedi un import `import torch` o `import cv2`
> al top di un file, è probabilmente un bug. Quei moduli pesanti vanno
> importati lazy dentro le funzioni che li usano.

### Frontend TypeScript

- **TypeScript strict mode** (`tsc --noEmit` deve passare con zero
  errori).
- **React 18 functional components** con hooks. Niente classi.
- **Niente Redux**: state via `useState`, `useReducer`, e Context
  Providers per cose globali (auth, theme, toast).
- **Tailwind utility classes**, niente CSS files custom (eccetto
  `index.css`).
- **API calls** sempre tramite `authFetch()` (auto-refresh JWT su 401).
- **Errori sempre catturati**: niente fetch nudo, sempre try/catch.

### Stile commit

Convenzione [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <descrizione corta>

<body opzionale, esplicare il "perché">

<footer opzionale, breaking change / co-author>
```

Tipi usati in CARA: `feat`, `fix`, `refactor`, `test`, `docs`,
`chore`, `merge`, `perf`.

Scope: `backend`, `frontend`, `api`, `ai`, `chat`, `voice`, `setup`,
`devices`, `skills`, `smarthome`, ... (di solito il modulo principale
toccato).

Esempi reali:

```
feat(skills): Phase C — Tier-2 cosine + Tier-3 LLM dispatcher
fix(setup): /reset advances past Step 1 when admin already exists
refactor(chat): Step 0.2 phase C — extract routing tiers into a dispatch loop
docs(prompt): first-run setup wizard spec
```

## 3.5 Branch e tag

### Branch strategy

CARA usa il modello **trunk-based** con branch tematici per Epic
grandi:

- **`main`** è sempre rilasciabile. Ogni commit su `main` deve passare
  i test.
- **Branch `epic-N-nome`** per lavori grandi che durano giorni o
  settimane. Esempi storici: `epic-0-foundations`, `epic-12-setup-wizard`,
  `epic-13-programmer-manual`.
- **Branch `fix/...`** per fix urgenti.
- Niente lunghi branch di feature paralleli — se due Epic toccano lo
  stesso file, fanno coda.

### Tag e versioni

CARA segue **SemVer**:

- **MAJOR.MINOR.PATCH**
- MAJOR: breaking change incompatibili (cambio schema DB non
  retrocompatibile, rimozione endpoint pubblico, ecc.)
- MINOR: nuove feature retrocompatibili
- PATCH: bug fix retrocompatibili

Tag attuali:

| Tag | Data | Descrizione |
|---|---|---|
| `v1.0.0` | 2026-05-05 | Prima release pubblica completa |
| `v1.1.0` | 2026-05-06 | Setup wizard `/setup` |

I tag sono annotati (`git tag -a vX.Y.Z -m "..."`) con messaggio
descrittivo, mai leggeri.

### Process di release

```bash
# 1. Conferma che main è verde
make test

# 2. Aggiorna CHANGELOG.md con la nuova entry
# Formato: vedi CHANGELOG.md per esempi

# 3. Bump versione frontend
cd frontend && npm version <major|minor|patch> --no-git-tag-version
cd ..

# 4. Commit del bump
git commit -m "chore(release): bump version to vX.Y.Z"

# 5. Tag annotato
git tag -a vX.Y.Z -m "CARA vX.Y.Z — short summary"

# 6. Build + deploy
DOCKER_BUILDKIT=0 docker compose --profile app build
docker compose --profile app up -d

# 7. Push (se hai un remote)
git push origin main
git push origin vX.Y.Z
```

## 3.6 Linguaggio + commenti

- **Codice in inglese**: variabili, funzioni, classi, file, commenti
  inline. Eccezione: stringhe utente-visibili (in italiano).
- **Docstring in inglese**: convenzione per compatibilità con tool di
  documentazione (Sphinx, ecc.).
- **UI utente in italiano**: labels, errori, placeholder, toast.
- **Documentazione (questo manuale, prompt, manuali utente) in italiano**:
  decisione del progetto.
- **Nomi di variabili "italiani-suonanti" sono permessi quando
  esprimono concetti senza traduzione** (es. `tone`, `tone_preset`).

> **💡 Suggerimento** — quando aggiungi un toast/error message nel
> frontend, scrivilo direttamente in italiano. CARA non è
> internazionalizzata di default; se serve, l'i18n si aggiunge dopo.

## 3.7 Cosa è gitignored

```
.env                # segreti
.env.*
data/postgres/*     # dump volume
data/minio/*
data/redis/*
data/chroma/*
data/uploads/*
data/models/*       # modelli AI (~2GB, riscaricabili)
__pycache__/
*.py[cod]
.venv/
node_modules/
dist/
.vite/
*.log
*.bak
build/twa/app/build/
build/twa/.gradle/
backups/*.sql.gz    # dump postgres
```

I dati restano sul filesystem, ma il git non li traccia. Questo
significa che `git clone` ti dà il codice ma **non** i dati — devi
ricreare il database, scaricare i modelli, ecc. Vedi cap 2.

---

[← Cap 2 Setup ambiente](02-setup-ambiente.md) · [README](README.md) · [Cap 4 Backend deep-dive →](04-backend-moduli.md)
