# CARA — Prompt di sviluppo: modulo `lifeops`

Sei il coding agent senior incaricato di implementare un nuovo modulo
applicativo di CARA chiamato **`lifeops`**: un insieme di capacità
operative quotidiane (promemoria, liste, note, contabilità personale)
fuse con le capacità relazionali e domestiche già native in CARA
(volto espressivo, routine famiglia, modalità sfogo, multi-utente,
storytelling, memoria fotografica).

L'ispirazione operativa viene dal prodotto commerciale **Planito**
(assistente AI su WhatsApp Business). L'obiettivo NON è portare
Planito dentro CARA: è **dare a CARA le stesse capacità operative
quotidiane, ma reinterpretate per un assistente di casa con volto,
voce e multi-utente nativo, on-device, senza Meta in mezzo**.

Lavori su un repository CARA esistente, con stack tecnico vincolato e
principi non negoziabili descritti sotto. Prima di scrivere una riga
di codice, devi capire cosa c'è già e proporre una struttura. Solo
dopo approvazione umana procedi.

---

## 0. Brief operativo

**Branch suggerito:** `feature/lifeops`, partendo dall'ultimo `main` o
da `feature/pwa-v2` se quel branch è ancora in flight (verificare con
`git log -1 main` e `git branch -a`).

**Convenzione commit:** Conventional Commits (`feat(lifeops): …`,
`fix(lifeops): …`, `test(lifeops): …`, `docs(lifeops): …`). Ogni
milestone = serie di commit atomici + un commit finale "release(M1)"
con tag `lifeops-m1`.

**Modello di lavoro:**

1. Leggi il repo (sezione 1), capisci cosa esiste, **non duplicare**.
2. Rispondi NON con codice ma con il payload definito al §2: riepilogo
   contestuale, 5 decisioni da confermare, struttura file proposta.
3. Aspetti approvazione umana scritta.
4. Implementi M1, smoke test, PR review, merge.
5. Ripeti per M2 e M3.

**Tutto in italiano** (commenti inglesi nei docstring tecnici sono OK
se necessari, ma stringhe UI, messaggi user-facing, prompt LLM tutti
italiani).

---

## 1. Contesto del repository CARA — leggere prima di scrivere

### 1.1 Stack tecnico — non modificabile

- **Backend:** Python 3.11, FastAPI, SQLAlchemy 2.x async, Alembic,
  PostgreSQL 16, Redis, Celery (5 worker code dedicate: `mail`,
  `files`, `learn`, `watchdog`/`health`, future `lifeops`), Pydantic
  v2, `uv` come package manager
- **Frontend:** React 18 + TypeScript strict, Vite, TailwindCSS,
  Zustand, TanStack Query, vite-plugin-pwa, WebRTC, Web Audio API
- **AI locale (NanoPC-T6, NPU RK3588 ~6 TOPS):** RKLLM con
  Qwen2.5-1.5B w8a8 (target 7B su hardware futuro, fallback 3B
  pianificato), sherpa-onnx ASR / faster-whisper, Piper TTS
  `it_IT-paola-medium`, Silero VAD, openWakeWord (in roadmap),
  sentence-transformers `paraphrase-multilingual-MiniLM-L12-v2`
  per embeddings, pgvector per facts + descrittori volto
- **Auth:** JWT + refresh token, ruoli famiglia (`parent | teen |
  child | elder | guest`) + `is_admin` ortogonale, WebAuthn previsto
- **DevOps:** Docker compose, single host NanoPC-T6, nginx-proxy in
  ascolto su porte `8443-8456`, Cloudflare Tunnel per accesso esterno

### 1.2 Cosa **deve esistere** nel repo prima di iniziare LifeOps

Esegui questi controlli e segnala se manca qualcosa:

```bash
# Modelli che lifeops userà come FK / decoratori
ls backend/cara/models/{user,family,audit,fact,task,note,reminder,event}.py 2>&1

# Servizi e API esistenti che NON va riscritti
ls backend/cara/services/{notify,family_bus,proactivity*,reminders,event_log}.py
ls backend/cara/api/v1/{tasks,notes,shopping,reminders,events,memory,family*}.py

# Infrastruttura Celery + Redis + family bus
grep -r "celery_app" backend/cara/tasks/
grep -r "publish.*family" backend/cara/services/family_bus.py
```

**ATTENZIONE — entità con possibile sovrapposizione:**

- `Reminder` (`models/reminder.py`) già esiste: 18 template "Vita
  Quotidiana" italiani, ricorrenze yearly/monthly/weekly, scheduler
  Celery, notifica via Telegram. **Non duplicare**. Estendi se serve.
- `Task` (`models/task.py`) già esiste: liste "da fare" minimali. Le
  liste `lifeops` sono concettualmente diverse (multi-lista, scope,
  drag&drop) ma devono coesistere — proponi se assorbire `tasks` in
  `lifeops_lists` o lasciarli separati.
- `Note` (`models/note.py`) già esiste: editor markdown con autosave.
  Lifeops dovrebbe estenderle con tag, ricerca semantica via
  embeddings (chromadb / pgvector), scope condivisione. **Estendi**,
  non sostituire.
- `ShoppingItem` (`models/shopping.py`) già esiste come lista
  predefinita. Migrazione naturale: `shopping` diventa una `List` con
  `slug='shopping'` in `lifeops_lists`, o resta separato e LifeOps
  si limita al "concetto lista" generico. **Proponi**, vedi §13.
- `Event`, `CalendarEvent` esistono. Non duplicare: il finance ha
  proprie transazioni, non sono eventi calendario.

### 1.3 Servizi che `lifeops` DEVE riusare (non riscrivere)

- `cara.services.notify` — bus notifiche multi-canale (push VAPID,
  Telegram, WebSocket family-bus). Reminders, conferme, alert
  passano da qui.
- `cara.services.family_bus` — Redis pub/sub interno per eventi
  presenza, TTS, proattività, tasks. LifeOps pubblica eventi tipo
  `lifeops.transaction.pending_confirm`, `lifeops.list.item_added`.
- `cara.services.reminders` — già fa scheduling + materializzazione
  notifiche. LifeOps eredita o estende, **non duplica** scheduler.
- `cara.services.proactivity` — engine regole proattive. Routine
  famiglia ricorrenti dovrebbero registrare regole qui, non un
  scheduler parallelo.
- `cara.ai.embeddings` + `cara.learning.semantic` — già fanno
  embeddings + retrieval. Notes lifeops + finance categorization
  usano questi servizi.
- `cara.ai.llm` — wrapper RKLLM con asyncio lock. Il router intent
  lifeops si serializza qui. Mai chiamare RKLLM direttamente.
- `cara.api.deps.require_user` / `require_admin` — auth deps. Usa
  esistenti, non scrivere nuovi.

### 1.4 Cosa NON è ancora nel repo (proponi tu)

- Nessun modello `Account`, `Transaction`, `FinanceCategory`.
- Nessun modello `List` (oltre `ShoppingItem` / `Task`).
- Nessun "router intent" lifeops-specifico.
- Nessuna UI `/lifeops/*` nel frontend (v2 ha `/list/*` + `/me/*` ma
  non un hub finance + multi-lista).

---

## 2. Prima azione richiesta — NON codice

Prima di scrivere una sola riga di codice o eseguire qualsiasi
migrazione, rispondi in chat (non in PR) con i tre payload qui sotto.

### 2.1 Riepilogo contestuale (max 30 righe)

Cosa hai capito del task. In particolare:

- Cosa esiste già nel repo che LifeOps userà come dependency
- Cosa esiste già che potrebbe collidere (es. `Reminder`, `Task`,
  `Note`, `ShoppingItem`) e come proponi di integrare senza duplicare
- Quale branch parent userai
- Come strutturerai il modulo (top-down)

### 2.2 Cinque decisioni di design da confermare

Lasciate aperte volutamente. Per OGNI decisione, fornisci la tua
proposta in 1-2 righe, e la motivazione in 1 riga. L'utente
risponderà "ok per tutte" o "modifica X così".

1. **Fusione Reminder esistente ↔ Reminder LifeOps**: estendo il
   modello esistente o ne creo uno nuovo (`LifeopsReminder`)?
2. **Fusione `ShoppingItem` ↔ `List` LifeOps**: assorbo shopping in
   `lifeops_lists` con migration di backfill, oppure resto separato?
3. **Categorie finance**: 12 globali seedate per famiglia, o
   ereditate da template + custom per famiglia?
4. **Conferma transazioni**: bloccante in chat (l'utente deve dire
   "sì confermo") o bloccante in UI (card pendente su volto / push)?
5. **Pending approval bambini**: chi è l'adulto di riferimento?
   primo `parent` della famiglia, o flag esplicito `is_supervisor`
   su `User`?

### 2.3 Struttura file proposta

Mostra l'albero `backend/cara/lifeops/`, `backend/cara/api/v1/lifeops*`,
`frontend-v2/src/routes/lifeops/`, `frontend-v2/src/api/lifeops*`.
Allinea ai pattern del repo esistente (verifica grep su come altri
moduli sono organizzati).

**Aspetta approvazione umana esplicita** ("ok procedi M1" o
equivalente) prima di toccare codice.

---

## 3. Architettura del modulo `lifeops`

### 3.1 Posizione nel grafo NLU di CARA

Il classificatore di dominio principale di CARA (esistente in
`backend/cara/services/intent_router.py` o equivalente — verifica
nel repo) routa una utterance verso uno dei domini: `chat_libera`,
`smart_home`, `storytelling`, `photo_memory`, `task`, `meteo`,
`news`, ecc.

LifeOps introduce **un nuovo nodo `lifeops_intent_router`** chiamato
**dopo** il classificatore di dominio principale e **prima** dei
router specifici già esistenti per domini sovrapposti (es. il
router task / shopping attuali).

Quando il classificatore di dominio dice "questo è probabilmente
una richiesta operativa quotidiana" (promemoria, lista, nota,
transazione, query finanziaria), il nodo `lifeops_intent_router`:

1. Riceve la trascrizione utente + contesto (vedi §6).
2. Chiama RKLLM con function calling / JSON mode.
3. Ritorna un intent tipizzato Pydantic.
4. Il dispatcher esegue l'azione (add reminder, add list item,
   record transaction…) oppure ritorna un fallback testuale se
   l'intent è ambiguo.

Quando il classificatore non capisce, la pipeline esistente di CARA
prosegue come oggi: chat_libera → LLM generativo.

### 3.2 Struttura cartelle attesa

Allinea ai pattern del repo. Proposta (verifica prima):

```
backend/cara/
├── lifeops/
│   ├── __init__.py
│   ├── intent_router.py      # NLU → Intent tipizzato
│   ├── intents.py            # Pydantic Intent classes
│   ├── prompts.py            # System prompts per l'LLM
│   ├── dispatchers/
│   │   ├── __init__.py
│   │   ├── reminders.py
│   │   ├── lists.py
│   │   ├── notes.py
│   │   └── finance.py
│   ├── nlu/
│   │   ├── __init__.py
│   │   ├── datetime_parser.py    # "tra 20 minuti", "domani 16:30"
│   │   ├── recurrence_parser.py  # "ogni lunedì alle 9"
│   │   ├── amount_parser.py      # "12 euro", "1.200 euro"
│   │   └── category_classifier.py
│   └── delivery/
│       ├── __init__.py
│       └── context_aware.py      # face + presence + mode → channel
├── models/
│   ├── lifeops_list.py           # List + ListItem
│   ├── lifeops_finance.py        # Account, Transaction, Category
│   └── lifeops_pending.py        # PendingApproval (bambini)
└── api/v1/
    ├── lifeops_lists.py
    ├── lifeops_finance.py
    ├── lifeops_pending.py
    └── lifeops_intent.py         # POST /lifeops/intent (debug / test)

backend/tests/
├── unit/
│   ├── test_lifeops_intent_router.py    # ≥30 frasi golden italiane
│   ├── test_lifeops_datetime_parser.py
│   ├── test_lifeops_recurrence_parser.py
│   ├── test_lifeops_amount_parser.py
│   └── test_lifeops_dispatchers.py
└── smoke/
    └── test_lifeops_e2e.py

frontend-v2/src/
├── api/
│   ├── lifeopsLists.ts
│   ├── lifeopsFinance.ts
│   └── lifeopsPending.ts
├── routes/
│   └── lifeops/
│       ├── LifeopsLayout.tsx
│       ├── ListsPage.tsx
│       ├── ListDetailPage.tsx
│       ├── FinancePage.tsx
│       ├── TransactionConfirmPage.tsx
│       └── PendingApprovalPage.tsx
└── components/
    └── lifeops/
        ├── ListItemRow.tsx
        ├── ListReorder.tsx       # drag&drop (dnd-kit, già presente?)
        ├── TransactionForm.tsx
        ├── CategoryChip.tsx
        └── FinanceCharts.tsx     # Recharts
```

### 3.3 Branch e flusso git

- `feature/lifeops` → contiene tutta M1, M2, M3
- Sub-branches solo se M1 → M3 sono parallelizzabili (probabilmente
  no, le dipendenze sono sequenziali)
- Tag `lifeops-m1`, `lifeops-m2`, `lifeops-m3` al merge di ogni
  milestone
- Niente force-push, niente rebase distruttivi
- Commit con `Co-Authored-By: Claude Opus … <noreply@anthropic.com>`
  in coda (convenzione del repo)

---

## 4. Modelli dati SQLAlchemy

Tutti i modelli `lifeops_*` ereditano da `cara.store.db.Base` e
seguono il pattern esistente del repo (verifica `models/reminder.py`
come riferimento più recente).

**Vincoli trasversali:**

- Ogni risorsa ha `user_id` (Integer, FK `users.id`, indexed, NOT NULL).
- Ogni risorsa ha `family_id` (Integer, FK `families.id`, indexed) —
  verifica se `families` esiste già o se va creato; se non esiste,
  proponi nel §2 di crearlo come prerequisito.
- `created_at`, `updated_at` con `server_default=func.now()`; NIENTE
  `onupdate=func.now()` (bug noto del repo: vedi CLAUDE.md "Quirks"
  — produce `MissingGreenlet` su async). `updated_at` aggiornato
  esplicitamente nel service.
- Timestamps: `DateTime(timezone=True)` con `nullable=False` per
  `created_at`. UTC ovunque in DB (vedi §13.3).
- Soft delete via `deleted_at: DateTime | None` — non hard delete,
  così l'audit trail è completo.

### 4.1 Reminders (estensione, non duplicazione)

Se il `Reminder` esistente ha solo i 18 template "Vita Quotidiana",
estendi così:

- Aggiungi colonna `source: String(24)` con valori `template |
  conversational | api`. Default `template` per i seed esistenti,
  `conversational` per quelli creati via voice/chat lifeops.
- Aggiungi colonna `urgent: Boolean` default `False`. Se `True`, il
  delivery passa SEMPRE, anche in modalità sfogo (vedi §13.6).
- Aggiungi colonna `delivery_context: JSONB | None` con schema:
  ```json
  {
    "preferred_channel": "screen_room|voice|push|telegram",
    "preferred_room": "cucina|salotto|...",
    "fallback_channels": ["push", "telegram"]
  }
  ```

Se invece il `Reminder` esistente è troppo accoppiato al template
flow per essere esteso pulitamente, **crea `LifeopsReminder`
separato** ma con UNICA tabella di scheduling (Celery + materialized
notifications) condivisa con il vecchio. Vedi §13.1 per RRULE.

### 4.2 Lists + ListItems

```python
class List(Base):
    __tablename__ = "lifeops_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    family_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("families.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    slug: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scope: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="user"
    )  # 'user' | 'family' | 'shared'
    color_token: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    archived_at: Mapped[datetime | None] = ...
    deleted_at: Mapped[datetime | None] = ...
    created_at: ...
    updated_at: ...

    __table_args__ = (
        UniqueConstraint("user_id", "slug", name="lifeops_list_user_slug_uq"),
        Index("lifeops_list_family_idx", "family_id"),
    )


class ListItem(Base):
    __tablename__ = "lifeops_list_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    list_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("lifeops_lists.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[int] = mapped_column(  # chi l'ha aggiunto
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    title: Mapped[str] = mapped_column(String(280), nullable=False)
    qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(24), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    done_at: Mapped[datetime | None] = ...
    done_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    sort_order: Mapped[int] = ...
    pending_approval: Mapped[bool] = mapped_column(  # vedi §8.6
        Boolean, nullable=False, server_default="false"
    )
    deleted_at: ...
    created_at: ...
    updated_at: ...
```

### 4.3 Notes (estensione)

Estendi `Note` esistente o crea `LifeopsNote` separato (verifica
acccoppiamenti):

- `tags: JSONB | None` — array di string
- `scope: String(16)` — `user|family|shared`
- `embedding: vector(384) | None` (pgvector) per ricerca semantica
- `archived_at: DateTime | None`

Pipeline di indicizzazione: al create/update, enqueue Celery task
`lifeops.notes.embed` che chiama `cara.ai.embeddings.embed_text` e
popola `embedding`. Ricerca via cosine top-k.

### 4.4 Finance — Account, Category, Transaction

```python
class Account(Base):
    __tablename__ = "lifeops_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = ...  # gli account sono sempre per-user
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    # 'cash' | 'bank' | 'card' | 'savings' | 'other'
    currency: Mapped[str] = mapped_column(String(3), nullable=False,
                                          server_default="EUR")
    balance_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )  # cached, ricalcolato da Celery (vedi sotto)
    archived_at: ...
    created_at: ...
    updated_at: ...


class FinanceCategory(Base):
    __tablename__ = "lifeops_finance_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = ...
    slug: Mapped[str] = mapped_column(String(48), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    # 'expense' | 'income'
    icon: Mapped[str | None] = ...
    color_token: Mapped[str | None] = ...
    is_system: Mapped[bool] = mapped_column(  # seed = system, custom = False
        Boolean, nullable=False, server_default="false"
    )

    __table_args__ = (
        UniqueConstraint("family_id", "slug"),
    )


class Transaction(Base):
    __tablename__ = "lifeops_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = ...  # sempre per-user, privacy by design
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("lifeops_accounts.id"), nullable=False, index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("lifeops_finance_categories.id"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )  # SEMPRE Numeric, MAI float — vedi §13.2
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    # 'expense' | 'income' | 'transfer'
    happened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    description: Mapped[str | None] = ...
    raw_utterance: Mapped[str | None] = ...
    # frase originale dell'utente, per audit / debug NLU
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="confirmed"
    )  # 'pending' | 'confirmed' | 'rejected'
    confirmed_at: ...
    deleted_at: ...
    created_at: ...
    updated_at: ...

    __table_args__ = (
        Index("lifeops_tx_user_when_idx", "user_id", "happened_at"),
    )
```

**Storage amount:** `Numeric(12, 2)` in DB → `Decimal` in Python.
`Decimal` viene serializzato come string nei JSON Pydantic (impostare
`field_serializer` o `Decimal2Str` custom type). **Mai float in
nessun punto del flusso finance.** Vedi §13.2.

`balance_cents` su Account è cached: viene ricalcolato da un Celery
task `lifeops.finance.recompute_balance` triggerato su create /
update / delete transaction. Lock distribuito (Redis) per evitare
race su update concorrenti.

### 4.5 Integrazione con entità esistenti

- **AuditLog**: ogni operazione lifeops scrive una entry con
  `action='lifeops.<dominio>.<verbo>'`, `target_kind`, `target_id`,
  `actor=user`, `ip`. Usa `audit_svc.record(...)` esistente.
- **FamilyBus**: pubblica eventi `lifeops.*` per WebSocket clients
  multi-tab (es. se Marina apre la spesa sul telefono e Antonio
  aggiunge "pane" dalla Wall, lo schermo di Marina aggiorna in
  real-time).
- **Routines** (se esiste o se l'agent lo crea come prerequisito):
  una routine famiglia tipo "sveglia mattutina" è modellata come un
  `Reminder` ricorrente con `recurrence_rrule` + `payload` che
  contiene una lista di `actions` da eseguire al fire (TTS, playback
  musica, render emozione su volto, push schermo specifico). Vedi §8.3.
- **Persona profiler / facts**: quando l'utente registra una
  transazione ricorrente o crea una lista nuova, il fact-extractor
  esistente può raccogliere segnali (es. "Antonio compra spesso al
  Conad" → fact con confidence). Non è prerequisito M1, ma il design
  deve lasciarlo possibile (espongono `episodic.record(...)`).

---

## 5. Endpoint REST FastAPI

Tutti gli endpoint sotto prefix `/api/v1/lifeops/...`. Auth
obbligatoria via `require_user`. Filtri `user_id` / `family_id`
in ogni query — niente "lista globale" raggiungibile.

Pattern per ogni dominio:

```python
@router.get("", response_model=list[ListOut])
async def list_lists(
    scope: Literal["user", "family", "all"] = "all",
    archived: bool = False,
    user: User = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> list[ListOut]:
    """Ritorna le liste visibili a quest'utente: sempre le `user`-scope
    proprie, opzionalmente quelle `family` se l'utente appartiene
    alla famiglia richiesta."""
```

### 5.1 Schema Pydantic

Definisci in `backend/cara/schemas/lifeops_*.py`:

- `ListOut`, `ListCreate`, `ListUpdate`
- `ListItemOut`, `ListItemCreate`, `ListItemUpdate`
- `AccountOut`, `AccountCreate`, `AccountUpdate`
- `FinanceCategoryOut`, `FinanceCategoryCreate`
- `TransactionOut`, `TransactionCreate`, `TransactionUpdate`,
  `TransactionConfirm`
- `PendingApprovalOut`, `PendingApprovalDecide`

Schema **non** espongono mai `family_id` di un'altra famiglia. Ogni
PATCH ricontrolla ownership dell'oggetto prima del commit.

### 5.2 Endpoint reminders

Se `Reminder` esiste già, estendi gli endpoint esistenti con i
nuovi campi (`source`, `urgent`, `delivery_context`). Aggiungi:

- `POST /api/v1/lifeops/reminders/from-intent` — riceve un
  `ReminderIntent` (struttura Pydantic prodotta dal router NLU) e
  crea il reminder schedulando notifiche. Auth: utente. Audit: SÌ.

### 5.3 Endpoint lists

- `GET /api/v1/lifeops/lists`
- `POST /api/v1/lifeops/lists` (body: `ListCreate`)
- `GET /api/v1/lifeops/lists/{id}`
- `PATCH /api/v1/lifeops/lists/{id}`
- `DELETE /api/v1/lifeops/lists/{id}` (soft delete)
- `POST /api/v1/lifeops/lists/{id}/items` (body: `ListItemCreate`)
- `PATCH /api/v1/lifeops/lists/{id}/items/{item_id}`
- `DELETE /api/v1/lifeops/lists/{id}/items/{item_id}`
- `POST /api/v1/lifeops/lists/{id}/items/{item_id}/done` (toggle)
- `POST /api/v1/lifeops/lists/{id}/reorder` (body: `[item_id, ...]`)
- `POST /api/v1/lifeops/lists/{id}/clear-done` (bulk delete done items)

### 5.4 Endpoint notes

Estendi `notes` esistenti con tag, scope, ricerca semantica:

- `GET /api/v1/lifeops/notes/search?q=...` — top-k via embedding
- `POST /api/v1/lifeops/notes/{id}/share` — cambia scope user→family

### 5.5 Endpoint finance

- `GET /api/v1/lifeops/finance/accounts`
- `POST /api/v1/lifeops/finance/accounts`
- `PATCH /api/v1/lifeops/finance/accounts/{id}`
- `GET /api/v1/lifeops/finance/categories`
- `POST /api/v1/lifeops/finance/categories` (solo custom famiglia)
- `GET /api/v1/lifeops/finance/transactions?from=&to=&account_id=&category_id=&direction=&state=`
- `POST /api/v1/lifeops/finance/transactions` — crea in stato
  `pending` se viene da NLU, `confirmed` se viene da UI manuale
- `POST /api/v1/lifeops/finance/transactions/{id}/confirm` — flip a
  `confirmed`, scrive audit, ricalcola balance
- `POST /api/v1/lifeops/finance/transactions/{id}/reject` — flip a
  `rejected`, no balance change
- `PATCH /api/v1/lifeops/finance/transactions/{id}` — solo se
  `state=confirmed` e l'utente è il proprietario
- `DELETE /api/v1/lifeops/finance/transactions/{id}` (soft)
- `GET /api/v1/lifeops/finance/summary?from=&to=&group_by=category|account|month`
  → riepilogo aggregato
- `POST /api/v1/lifeops/finance/import-csv` (multipart) — import
  bancario, dry-run di default, commit se `?commit=true`
- `GET /api/v1/lifeops/finance/export.csv?from=&to=` — export
  commercialista, formato standard

### 5.6 Endpoint pending approval

- `GET /api/v1/lifeops/pending` — items in pending per l'utente che
  ha permessi di supervisione
- `POST /api/v1/lifeops/pending/{id}/approve`
- `POST /api/v1/lifeops/pending/{id}/reject`

### 5.7 Endpoint intent (debug + test)

- `POST /api/v1/lifeops/intent` — body: `{utterance: str}` →
  ritorna l'`Intent` parsato senza eseguire l'azione. Utile per
  debug, per il /admin diagnostics, per i test golden. Gate dietro
  `require_admin` in produzione.

---

## 6. Router intent NLU

### 6.1 Contratto

Input (`IntentRequest` Pydantic):

```python
class IntentContext(BaseModel):
    user_id: int
    family_id: int | None
    user_role: Literal["parent", "teen", "child", "elder", "guest"]
    user_first_name: str
    current_mode: Literal["normal", "sfogo", "silent", "storytelling"]
    room_hint: str | None  # da face recognition + presence
    accounts: list[AccountSummary]
    categories: list[FinanceCategorySummary]
    lists: list[ListSummary]
    now_iso: str  # ISO8601 con offset Europe/Rome
    locale: Literal["it"] = "it"


class IntentRequest(BaseModel):
    utterance: str
    context: IntentContext
```

Output (`Intent` discriminated union):

```python
class ReminderIntent(BaseModel):
    kind: Literal["reminder"] = "reminder"
    title: str
    fires_at: datetime | None  # absolute
    rrule: str | None          # se ricorrente
    urgent: bool = False
    delivery_hint: str | None  # "in cucina", "via push"

class ListAddIntent(BaseModel):
    kind: Literal["list_add"] = "list_add"
    list_slug: str
    item: str
    qty: float | None = None
    unit: str | None = None

class ListQueryIntent(BaseModel):
    kind: Literal["list_query"] = "list_query"
    list_slug: str | None

class ListDoneIntent(BaseModel):
    kind: Literal["list_done"] = "list_done"
    list_slug: str
    item_substring: str

class NoteAddIntent(BaseModel):
    kind: Literal["note_add"] = "note_add"
    body: str
    title: str | None = None
    tags: list[str] = []

class NoteSearchIntent(BaseModel):
    kind: Literal["note_search"] = "note_search"
    query: str

class TransactionAddIntent(BaseModel):
    kind: Literal["transaction_add"] = "transaction_add"
    amount: Decimal
    direction: Literal["expense", "income"]
    description: str
    category_slug: str | None = None
    account_name: str | None = None
    happened_hint: str | None = None  # "ieri", "stamattina"

class FinanceQueryIntent(BaseModel):
    kind: Literal["finance_query"] = "finance_query"
    metric: Literal["sum", "avg", "count"]
    direction: Literal["expense", "income"] | None
    category_slug: str | None
    account_name: str | None
    from_hint: str | None
    to_hint: str | None

class UnsureIntent(BaseModel):
    kind: Literal["unsure"] = "unsure"
    reason: str
    suggested_clarification: str  # frase da TTS

Intent = Annotated[
    ReminderIntent | ListAddIntent | ListQueryIntent | ListDoneIntent
    | NoteAddIntent | NoteSearchIntent | TransactionAddIntent
    | FinanceQueryIntent | UnsureIntent,
    Field(discriminator="kind"),
]
```

### 6.2 Function calling con Qwen2.5

RKLLM al momento (vedi `cara.ai.llm`) NON espone una function-calling
API nativa pulita. Usa il pattern **JSON-mode con prompt**:

- System prompt italiano che descrive lo schema, le funzioni
  disponibili, gli esempi.
- Few-shot in-prompt con 8-12 esempi italiani realistici.
- L'LLM ritorna SOLO JSON dell'union `Intent`.
- Parser: `Intent.model_validate(json.loads(raw))`. Se fallisce,
  retry con prompt "correggi il JSON". Se anche il retry fallisce,
  `UnsureIntent`.

Esempio frammento di prompt (italiano):

```
Sei il router intent del modulo Lifeops di CARA. Ricevi una frase
detta da {user_first_name} ({user_role}) alle {now_iso}.

Categorie di intent disponibili, una sola per output, formato JSON
discriminato:
- reminder: per "ricordami / promemoria / tra X / domani alle Y"
- list_add | list_query | list_done: liste {list_slugs}
- note_add | note_search: appunti / pensieri da salvare
- transaction_add: registra una spesa o un'entrata
- finance_query: domande di riepilogo finanziario
- unsure: se la frase non è chiaramente operativa o è ambigua

Liste esistenti per {user_first_name}: {list_summaries}
Account esistenti: {account_summaries}
Categorie finance: {category_summaries}

REGOLE:
1. Se non capisci con certezza, usa "unsure" con suggested_clarification.
2. Per "transaction_add", non inventare account/categoria se non sei
   sicuro; ritorna i campi vuoti — saranno chiesti in UI.
3. Per "reminder", risolvi le date/ore in ISO 8601 UTC. Se è
   relativa ("tra 20 minuti"), calcola partendo da {now_iso}.
4. Per "reminder" ricorrenti, ritorna anche un RRULE RFC 5545.
5. NON aggiungere campi non previsti dallo schema.
6. NON rispondere in linguaggio naturale: solo JSON.

ESEMPI:
[utente: "ricordami di chiamare il medico domani alle 16:30"]
→ {"kind": "reminder", "title": "Chiamare il medico",
   "fires_at": "2026-05-23T14:30:00Z", "rrule": null, "urgent": false}

[utente: "ogni lunedì alle 9 butta la carta"]
→ {"kind": "reminder", "title": "Buttare la carta",
   "fires_at": null,
   "rrule": "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0",
   "urgent": false}

[utente: "aggiungi detersivo alla spesa"]
→ {"kind": "list_add", "list_slug": "shopping", "item": "Detersivo"}

[utente: "ho speso 12 euro in farmacia"]
→ {"kind": "transaction_add", "amount": "12.00",
   "direction": "expense", "description": "Farmacia",
   "category_slug": "salute"}

[utente: "che tempo fa?"]
→ {"kind": "unsure",
   "reason": "richiesta meteo, fuori dominio lifeops",
   "suggested_clarification": "Per il meteo dimmi 'che tempo fa oggi'."}

UTTERANCE: {utterance}
OUTPUT (solo JSON, niente altro):
```

### 6.3 Posizione nel grafo (vedi §3.1)

Il dispatcher centrale di CARA chiama `lifeops.intent_router.route(
request)` se il classificatore di dominio principale ha etichettato
l'utterance come `domain in {lifeops, list, reminder, finance, note,
shopping, task}`. Altrimenti la pipeline esistente prosegue.

### 6.4 Test obbligatori (≥30 frasi golden)

`backend/tests/unit/test_lifeops_intent_router.py` deve avere
**almeno 30 casi italiani realistici**, copertura per:

- reminders con datetime assoluto, relativo, RRULE settimanale,
  RRULE mensile, urgente
- list_add con quantità ("aggiungi 2 chili di pomodori"),
  list_done con substring, list_query
- note_add con e senza titolo, note_search semantica
- transaction_add con vari formati monetari ("12 euro", "1.200",
  "1,50", "trecento euro"), direction inferita
- finance_query: sum mese, sum categoria, sum account, anno corrente
- unsure: meteo, smart home, chat aperta, frasi-trappola

Per ogni test: input italiano + Intent atteso come dict; assert
`Intent.model_validate(actual).model_dump() == expected_dict`.

Mockare RKLLM con un fake che ritorna risposte canned (basate su
regex sul prompt) — niente NPU in CI.

---

## 7. Scheduler Celery

### 7.1 Reuse del Celery esistente

Il repo ha già 4 worker code: `mail`, `files`, `learn`, `watchdog`
(+ beat). **Aggiungi `lifeops`** come 5° coda dedicata (container
`cara-celery-lifeops`, IP statico in proxy-net, `LLM_ENABLED=false`
come gli altri worker, lock RKLLM accessibile solo dal backend
principale).

Task in `backend/cara/agents/lifeops.py`:

- `lifeops.reminders.scan_due` — ogni 60s, cerca notifiche
  materializzate con `scheduled_at <= now AND sent_at IS NULL`,
  enqueue su family-bus → backend consumer fa dispatching context-aware.
- `lifeops.reminders.materialize_rrule` — ogni notte 03:30, per ogni
  reminder con RRULE espande le occorrenze future N giorni avanti
  in `reminder_notifications`. Idempotente.
- `lifeops.finance.recompute_balance` — triggerata on-demand al
  commit di una transaction. Lock distribuito Redis per evitare race.
- `lifeops.notes.embed` — su create/update, calcola embedding e
  popola `notes.embedding`.

Configurazione in `backend/cara/tasks/celery_app.py`:

```python
task_routes = {
    "cara.agents.lifeops.*": {"queue": "lifeops"},
    ...
}
beat_schedule = {
    "lifeops-reminders-scan-due": {
        "task": "cara.agents.lifeops.scan_due",
        "schedule": 60,  # secondi
    },
    "lifeops-reminders-materialize-nightly": {
        "task": "cara.agents.lifeops.materialize_rrule",
        "schedule": crontab(hour=3, minute=30),
    },
}
```

### 7.2 Integrazione con notify bus

Il task `scan_due` NON chiama push/telegram/WS direttamente: pubblica
una `Notification` su Redis bus. Il backend consumer (esistente,
vedi `cara.services.notify.consume_dispatch_bus`) prende le
notifiche e le fan-out su tutti i canali abilitati per l'utente.

Per LifeOps aggiungiamo un'estensione: il dispatcher chiama
**`lifeops.delivery.context_aware.choose_channel(notif, user, now)`**
prima di mandare. Vedi §8.1.

---

## 8. Comportamenti di fusione (Planito ↔ CARA)

Queste sono **le regole che rendono lifeops "CARA" e non "Planito
in WhatsApp"**. Implementale fedelmente, sono il prodotto.

### 8.1 Delivery context-aware (face + presence + room)

`lifeops.delivery.context_aware.choose_channel(notif, user, now)`
ritorna un `DeliveryPlan`:

```python
class DeliveryPlan(BaseModel):
    channels: list[Literal["screen_room", "voice", "push", "telegram", "queue"]]
    room: str | None
    voice_text: str | None
    push_payload: dict | None
    queue_reason: str | None  # se channel='queue'
```

Tabella decisionale (vedi §13.5):

| Stato CARA | Utente in casa? | Stanza nota? | Sconosciuto in stanza? | Channels |
|---|---|---|---|---|
| `normal` | sì | sì | no | `screen_room` + `voice` |
| `normal` | sì | no | — | `push` + `voice (low)` |
| `normal` | no | — | — | `push` + `telegram` |
| `normal` | sì | sì | sì | `push` (no voice, no schermo) |
| `silent` o `sfogo` | qualsiasi | — | — | `queue` (tranne urgent=true) |
| `storytelling` | bambino è target | — | — | `queue` se non urgent |

Note:

- `urgent=true` bypassa SEMPRE `queue` (es. promemoria farmaci).
- Se il modello vocale non è disponibile (Piper offline), degrade a
  push silenziosa con title+body.
- Se l'utente ha disabilitato `notify_voice_message_enabled` nel
  profilo, niente TTS in nessun caso.

### 8.2 Modalità sfogo / presenza silenziosa

Stato in `users` (o `families`?): `current_mode: Literal["normal",
"sfogo", "silent", "storytelling"]`. Settato da:

- Comando esplicito ("CARA, lasciami in pace per un'ora" → `silent`
  per 60min, poi reset)
- Inferenza di tono dalla chat (in roadmap, niente nella M1)
- Toggle UI in `/me/settings`

In modalità non-`normal`:

- Notifiche operative → `queue_reason="sfogo"`, materializzate per
  consegna deferita
- Il volto CARA non interrompe con suggerimenti
- L'avatar mostra emotion `quiet` / `gentle`
- Promemoria con `urgent=true` arrivano comunque, con un format
  attenuato ("Antonio, scusa il disturbo. Promemoria farmaco delle 14.")

Quando torna `normal`: il backend consumer scoda le notifiche
accodate, le ri-dispatcha rispettando ordine cronologico + soglie
spam (max 3 raggruppate, le altre in summary).

### 8.3 Routine famiglia come reminder ricorrenti multimediali

Una "routine famiglia" non è un'entità nuova: è un `Reminder`
ricorrente con:

- `recurrence_rrule` (RRULE RFC 5545)
- `scope='family'` (assegnato a tutta la famiglia)
- `delivery_context.actions` JSON con sequenza azioni:
  ```json
  {
    "actions": [
      {"kind": "tts", "voice_text": "Buongiorno Sara, sono le sette."},
      {"kind": "play_radio", "station": "Radio Capital"},
      {"kind": "face_emotion", "emotion": "happy_warm", "duration_s": 30},
      {"kind": "screen", "room": "camera_sara", "view": "morning_dashboard"}
    ],
    "preferred_room": "camera_sara",
    "fallback_channels": []
  }
  ```

Al fire del reminder, il dispatcher esegue le `actions` in sequenza
(con timeout per ognuna, fallback graceful se una fallisce — es.
radio offline → skip).

UI per gestire routine: estensione di `/lifeops/routines/*` o
sottosezione di reminders con filtro `is_routine=true`.

### 8.4 Conferma esplicita transactions (no auto-commit)

Quando un `TransactionAddIntent` arriva dal router NLU:

1. Crea transaction con `state='pending'`.
2. Pubblica `Notification(kind='lifeops.transaction.pending_confirm',
   user_id=user.id, payload={transaction})`.
3. Il dispatch context-aware sceglie il canale (di solito
   `screen_room` + `voice` se l'utente è in stanza, altrimenti push).
4. UI: card con i campi pre-compilati (`amount`, `direction`,
   `category`, `account`, `description`, `happened_at`) + bottoni
   `[Confermo]` `[Modifica]` `[Annulla]`.
5. Solo dopo `[Confermo]` (POST `.../confirm`) la transaction passa
   a `state='confirmed'` e il balance ricalcolato.
6. Se entro 60min nessuna conferma e l'utente non è loggato,
   notifica push "Hai una spesa in sospeso: 12€ farmacia. Confermi?".
7. Se entro 24h ancora nessuna conferma, auto-`rejected` con audit.

**Razionale:** "ho speso 12 euro" detto a voce in casa può essere
intercettato dal mic mentre era diretto a un familiare. Confermare
sempre evita allucinazioni di Whisper + falsi positivi NLU + doppie
registrazioni.

### 8.5 Scope user / family / shared

| Risorsa | Scope di default | Override possibile? |
|---|---|---|
| Reminder | user | sì → family (routine) |
| List | user | sì → family (esplicito) |
| ListItem | eredita dalla lista | no |
| Note | user | sì record-per-record (no global flip) |
| Account | sempre user | mai shared |
| Transaction | sempre user | mai shared |
| FinanceCategory | sempre family | n/a |

**Notes private:** anche con `scope='family'`, le note di Antonio
non sono leggibili da Marina senza esplicita azione `POST
.../share/{user_id}`. Niente "everything is family by default".

### 8.6 Pending approval per bambini

Quando un utente con `role='child'` (o `role='teen'`) tenta di
modificare una risorsa `scope='family'` (es. aggiunge "caramelle"
alla lista spesa famiglia):

1. L'azione viene salvata in `lifeops_pending_approvals`:
   ```python
   class PendingApproval(Base):
       __tablename__ = "lifeops_pending_approvals"
       id: int
       requested_by_user_id: int
       supervisor_user_id: int  # vedi sotto
       target_kind: str   # 'list_item' | 'transaction' | ...
       target_payload: JSONB
       state: Literal['pending', 'approved', 'rejected', 'expired']
       expires_at: datetime  # default +48h
       created_at: ...
   ```
2. L'item appare in lista con `pending_approval=true`, mostrato in
   UI con icona "lock" + tooltip "in attesa di approvazione".
3. Notifica push al `supervisor_user_id` (primo `parent` della
   famiglia, o `is_supervisor=true` se quella flag esiste — vedi §2.2).
4. Supervisor approva → `pending_approval=false`, push al child
   ("Mamma ha approvato 'caramelle' nella spesa.").
5. Supervisor rifiuta → item soft-deleted, notifica gentile al child.
6. Scadenza 48h senza decisione → auto-`expired`, item resta come
   "sospeso" finché un adulto interviene.

**Eccezione:** i child possono modificare liste con `scope='user'`
proprie senza approvazione (la loro lista cose da fare).

### 8.7 Storytelling / hobby mode

Quando CARA rileva (dal classificatore di dominio) che la richiesta
è "raccontami una storia" o "giochiamo a..." o "aiutami con i
compiti", **NON entra in lifeops_intent_router**. La pipeline va
direttamente al modulo storytelling esistente.

Lifeops registra questo stato come `current_mode='storytelling'`
nell'utente (il bambino, non l'adulto) per il tempo della sessione,
così le delivery operative per QUEL bambino vanno in queue. Per gli
altri utenti della famiglia il dispatch resta normale.

---

## 9. Frontend PWA

### 9.1 Routes

Aggiungi sotto `/lifeops` (o sotto i path che la PWA v2 già usa —
verifica se ha `/list/*` e `/me/*` esistenti e dove ha senso
agganciarsi).

```
/lifeops                    → LifeopsLayout (tabs)
/lifeops/lists              → ListsPage
/lifeops/lists/:slug        → ListDetailPage
/lifeops/notes              → NotesPage (estensione esistente)
/lifeops/notes/:id          → NoteEditorPage
/lifeops/finance            → FinanceOverviewPage
/lifeops/finance/accounts   → AccountsPage
/lifeops/finance/transactions → TransactionsListPage
/lifeops/finance/transactions/:id/confirm → TransactionConfirmPage
/lifeops/pending            → PendingApprovalPage (solo adulti)
/lifeops/reminders          → RemindersPage (estensione)
```

### 9.2 Componenti chiave

- `LifeopsLayout`: shell con tabs (Liste, Note, Finance, Promemoria,
  Pending) + breadcrumb + integrazione con `FloatingAvatar` per
  pre-conferme inline.
- `ListItemRow`: row swipe-to-action (left = done, right = delete),
  drag handle via `dnd-kit` (se non presente già, valuta
  alternative; preferenza per dipendenze esistenti).
- `TransactionConfirmCard`: card a tutto schermo con tutti i campi
  della transazione pre-compilati dall'NLU, bottoni grandi
  `[Confermo]` `[Modifica]` `[Annulla]`. Quando aperta, il volto
  CARA passa a emotion `attentive`.
- `FinanceCharts`: usa Recharts (verifica se già nel package.json,
  altrimenti proponi nei §2.5). Charts: pie categoria, bar mensile,
  trend annuale.
- `MarkdownEditor` per le notes: usa un editor lightweight (es.
  `react-textarea-autosize` + parser markdown lato render), no
  WYSIWYG pesanti.
- `PendingApprovalCard`: usato sia dall'adulto (per
  approvare/rifiutare) sia dal child (per vedere lo stato delle
  proprie richieste).
- `FaceCaraPreConfirm`: componente che mostra il volto CARA con
  un'animazione "sto chiedendo conferma" — pulse + emotion warm
  attentive. Riusa l'avatar provider esistente.

### 9.3 Stato condiviso

- **TanStack Query** per server state, query keys consistenti:
  `['lifeops', 'lists']`, `['lifeops', 'lists', listId, 'items']`,
  `['lifeops', 'finance', 'transactions', filters]`.
- **Zustand** per UI state (selectedListId, filter banner aperto,
  ecc.).
- **Family-bus WebSocket** sottoscritto a topic `lifeops.*` per
  invalidate ottimistico delle query quando arrivano eventi da
  altri client (es. Marina chiude un task → lo schermo di Antonio
  aggiorna in 100ms senza polling).

### 9.4 Drag & drop, ricerca semantica, chart

- Drag&drop liste: `dnd-kit` se presente nel repo, altrimenti
  proponi alternativa con touch handlers nativi (no jQuery-UI mai).
- Ricerca semantica notes: input `<TextInput>` con debounce 300ms,
  chiamata a `GET /lifeops/notes/search?q=...`, lista risultati con
  highlight della frase più simile (estratta server-side).
- Chart finance: Recharts. Default theme allineato ai design token
  del repo (`cara.frontend.theme`).

### 9.5 Accessibilità

- Aria-label su tutti i bottoni icona-only
- Touch target min 44x44 px (Apple HIG)
- High-contrast mode preset (per Ilaria / ospiti anziani — design
  token già pensato per questo, verifica)
- TTS auto-read della card conferma transazione se l'utente ha
  `prefers-reduced-text=true` (proponi flag in `users`).

---

## 10. Migrazione Alembic + seed idempotente

### 10.1 Migrations

Crea una unica revision Alembic `lifeops_m1_initial_<rev>` con
TUTTE le table M1 (`lifeops_lists`, `lifeops_list_items`,
`lifeops_accounts`, `lifeops_finance_categories`,
`lifeops_transactions`, `lifeops_pending_approvals`, e le ALTER su
`reminders`/`notes` se decisi di estenderle).

Reversibile: `downgrade()` ripristina lo stato pre-migrazione.

### 10.2 Seed categorie finance famiglia (12 italiane realistiche)

`backend/cara/lifeops/seed_categories.py`, funzione idempotente
`ensure_default_categories(session, family_id)`:

| slug | label | direction | icon | colore (token) |
|---|---|---|---|---|
| `casa` | Casa & utenze | expense | `home` | `slate-500` |
| `spesa` | Spesa & alimentari | expense | `shopping-cart` | `emerald-500` |
| `trasporti` | Trasporti & carburante | expense | `car` | `sky-500` |
| `salute` | Salute & farmacia | expense | `cross` | `rose-500` |
| `bimbi` | Bimbi & scuola | expense | `child` | `amber-500` |
| `ristoranti` | Ristoranti & bar | expense | `coffee` | `orange-500` |
| `tempo_libero` | Tempo libero | expense | `popcorn` | `violet-500` |
| `abbonamenti` | Abbonamenti & servizi | expense | `repeat` | `indigo-500` |
| `regali` | Regali & cerimonie | expense | `gift` | `pink-500` |
| `altre_spese` | Altre spese | expense | `dots` | `zinc-500` |
| `stipendio` | Stipendio & compensi | income | `briefcase` | `green-600` |
| `entrate_varie` | Entrate varie | income | `arrow-down` | `green-500` |

Eseguita una sola volta per famiglia, alla prima creazione famiglia
o al primo POST `/lifeops/finance/categories` se la famiglia ne ha 0.

### 10.3 Account "Contanti" per utente

Al primo accesso al modulo Finance di un utente, crea
automaticamente un account `name="Contanti"`, `kind="cash"`,
`currency="EUR"`, `balance_cents=0`. Idempotente: se esiste già,
no-op.

### 10.4 Liste predefinite

Per ogni utente nuovo (o esistente alla prima migration), crea:

- `slug="todo"`, `title="Da fare"`, `scope="user"`, icon `check`
- `slug="shopping"`, `title="Spesa"`, `scope="family"`, icon
  `shopping-cart`

Se `ShoppingItem` esiste già con dati, M1 propone una migration di
backfill che importa gli item esistenti nella nuova lista
`shopping`. Vedi §2.2 decisione 2.

---

## 11. Privacy by design

### 11.1 Audit log — cosa SÌ

- Ogni `POST` / `PATCH` / `DELETE` su risorse lifeops scrive una
  entry in `audit_log` con: `actor_user_id`, `action`, `target_kind`,
  `target_id`, `created_at`, `ip`, `family_id` (per filtraggio
  successivo). Il `detail` JSON contiene un diff schematico SENZA
  contenuti sensibili (es. per transactions registra `amount` ma NON
  la `description` o `raw_utterance` perché possono contenere PII —
  vedi §11.2).
- Ogni `confirm` / `reject` su transactions o pending_approvals.
- Ogni cambio di `current_mode` utente.

### 11.2 Logging strutturato — cosa MAI nei log

**Mai loggare:**

- `raw_utterance` di transazioni o note (può contenere nomi,
  importi, dati medici, ecc.)
- Contenuto `body` di note
- `description` di transazioni
- Dati di terze persone menzionate in promemoria
- Token JWT, password, refresh token (ovviamente)
- IP detail oltre quello già necessario per audit (max /24)

**SÌ loggare** (structured JSON, level INFO):

- Counter aggregati: `lifeops.intent.count{kind='reminder'}`
- Errori NLU classificati: `lifeops.intent.unsure_rate`
- Durata operazioni: `lifeops.transaction.create_duration_ms`
- Eventi pending_approval: solo conta + scadenze

### 11.3 Export utente (GDPR Art. 15)

Endpoint `POST /api/v1/lifeops/export` (auth user) → genera un JSON
con TUTTI i dati lifeops di quell'utente: reminders, lists owned +
condivise dove è proprietario, notes, transactions, accounts,
pending_approvals come richiedente. Streamed download. Audit log
dell'export stesso.

### 11.4 Cancellazione (GDPR Art. 17)

Endpoint `POST /api/v1/lifeops/purge` (auth user, conferma double
opt-in via password re-prompt o WebAuthn): soft-delete tutto + log
del purge. Hard delete fisico schedulato 30 giorni dopo da Celery
task. Account family-scoped (es. routine condivise create
dall'utente) restano con autore anonimizzato (`requested_by_user_id
= NULL`).

### 11.5 Encryption at rest

`Note.body`, `Transaction.description`, `Transaction.raw_utterance`,
`Reminder.title` (quando contiene info medicali — flag opzionale):
considera encryption at rest con chiave per famiglia, gestita da
`cara.crypto` (se esiste — verifica). Se non esiste, **non
implementare in M1**, ma proponilo come M4 / hardening successivo.

DB-level: TLS sulla connessione PostgreSQL già in compose
(verifica). Postgres data dir su disco LUKS-cifrato dell'host
(decisione sysadmin, non sviluppo).

---

## 12. Test obbligatori

### 12.1 Pytest endpoint

`backend/tests/unit/test_lifeops_*.py`:

- Per ogni endpoint: 200 happy path, 401 senza auth, 403 cross-user,
  404 not-found, 422 schema violation, 409 conflict (es. slug
  duplicato), 200 con filtri.
- Soft-delete: assert che `deleted_at` è settato, `GET` non lo
  ritorna di default, `?include_deleted=true` lo ritorna.
- Family scope: utente A non vede risorse di famiglia B.

### 12.2 Pytest router intent (golden ≥30 frasi)

Vedi §6.4. File: `test_lifeops_intent_router.py`. Mockare LLM con
fake basato su regex/keyword (no NPU in CI). Eseguire anche un
test integrazione opzionale (skip se NPU non disponibile) che usa
l'LLM vero.

### 12.3 Vitest componenti React

`frontend-v2/src/routes/lifeops/__tests__/*.test.tsx`:

- TransactionConfirmCard: render con dati pre-compilati, click
  conferma chiama mutation, error state, loading state.
- ListItemRow: swipe interaction (jsdom + simulate touch), done
  toggle ottimistico.
- FinanceCharts: smoke render con dati mock.

### 12.4 Playwright E2E (smoke)

`frontend-v2/e2e/lifeops.spec.ts`:

1. Login → vai a `/lifeops/lists` → crea lista nuova → aggiungi 3
   item → marca uno done → vedi badge counter.
2. Login → vai a `/lifeops/finance` → crea account → registra
   transazione manuale → conferma → vedi balance aggiornato.
3. Da `/admin/diagnostics` invia un utterance al `POST
   /lifeops/intent` con `{"utterance": "ricordami di chiamare il
   medico domani alle 16:30"}` → verifica response Intent valido
   discriminator=reminder.

Tutti i test devono passare prima del merge di ogni milestone.

---

## 13. Decisioni già prese — non rinegoziare

### 13.1 RRULE vs occorrenze materializzate

**Decisione: ibrido. RRULE è canonical, occorrenze N giorni in
avanti materializzate.**

Razionale: l'RRULE RFC 5545 è canonical e compatto in DB
(`recurrence_rrule: String(280)`). Ma i task Celery che fanno scan
ogni 60s NON parsano l'RRULE: leggono righe già materializzate in
`reminder_notifications` con `scheduled_at`. Il task notturno
`materialize_rrule` espande RRULE → N occorrenze (default 30 giorni
avanti) e popola la tabella. Idempotent via UNIQUE (`reminder_id`,
`scheduled_at`).

### 13.2 Storage amount

**`Numeric(12, 2)` in DB, `Decimal` in Python, mai float.**

Pydantic serializer: `Decimal` → string nel JSON
(`field_serializer('amount')` che ritorna `str(value)`). I client
parsano la string in Decimal locale (libreria JS `decimal.js` se
serve aritmetica, altrimenti format come display).

### 13.3 Timezone

**Tutto in UTC nel DB. `Europe/Rome` solo al boundary (input UI,
output UI, NLU now_iso, render). Datetime sempre `tzinfo`-aware,
mai naive.**

Helper in `cara.lifeops.tz`:

```python
ROME = ZoneInfo("Europe/Rome")

def now_utc() -> datetime: return datetime.now(timezone.utc)
def now_rome() -> datetime: return datetime.now(ROME)
def to_utc(dt: datetime) -> datetime: ...
def to_rome(dt: datetime) -> datetime: ...
```

### 13.4 Posizione del router intent nel grafo NLU

**Nuovo nodo `lifeops_intent_router` dopo il classificatore di
dominio principale, prima dei router specifici esistenti
(storytelling, photo, memory).** Vedi §3.1.

### 13.5 Tabella di delivery promemoria

Vedi §8.1 — tabella decisionale completa. Implementala come pure
function in `lifeops.delivery.context_aware`, testata in pytest con
30+ scenari.

### 13.6 Gerarchia delle modalità

**Ordine di priorità (alto vince):**

1. `urgent=true` su reminder/notification → consegna sempre, in
   tutte le modalità, con tono attenuato in sfogo/silent.
2. `current_mode='sfogo'` o `'silent'` → notifiche operative non
   urgenti accodate finché non torna `normal`.
3. `current_mode='storytelling'` → solo l'utente target del
   storytelling è in queue mode; gli altri normali.
4. `current_mode='normal'` → tutto normale.

Cambi di modalità: audit log SÌ, broadcast su family-bus SÌ (così la
UI di tutti aggiorna l'avatar CARA).

### 13.7 Categorie finance seed

Vedi §10.2 — lista finale di 12 categorie italiane realistiche. È
quella, non modificarla.

### 13.8 Pending approval per bambini

**Default supervisor:** il primo `parent` della famiglia (per
`users.created_at` ASC). Override possibile con flag
`is_supervisor=true` su `users` (proponilo come migration M1).
Pending approvals scadono dopo 48h con auto-`expired`. Vedi §8.6.

---

## 14. Cose da NON fare — vincoli espliciti

- ❌ **Niente WhatsApp Business API**, niente Meta, niente Twilio
  per WhatsApp. CARA vive in casa.
- ❌ **Niente dipendenze npm/pypi nuove** se quelle già in
  `package.json` / `pyproject.toml` bastano. Se proprio serve,
  giustifica nel §2.2.
- ❌ **Niente cloud LLM senza opt-in di sessione**. RKLLM locale è
  il default. Cloud (OpenAI/Anthropic) accessibile solo se l'utente
  attiva esplicitamente "modalità cloud" per la sessione corrente
  (no salvataggio permanente del flag).
- ❌ **Niente `any` / `Any` / `unknown` non motivati** in TypeScript
  o type stubs Python.
- ❌ **Niente `TODO` o `FIXME` nei commit di merge**. Se serve
  rimandare qualcosa → issue GitHub + commento nel codice
  `# Tracked: issue #N`.
- ❌ **Niente auto-conferma sulle transazioni**. Sempre `pending`
  via NLU, `confirmed` solo dopo azione esplicita.
- ❌ **Niente notifiche operative durante `sfogo` o `silent`**,
  tranne quelle `urgent=true`.
- ❌ **Niente float per amount** in nessun layer (DB, ORM, API,
  serializer, UI).
- ❌ **Niente endpoint senza filtro `user_id` / `family_id`**.
  Mai una query "tutto il database" raggiungibile da un client.
- ❌ **Niente seed di dati di test in produzione**. Il seed delle
  12 categorie e degli account default è OK; nomi tipo "Mario
  Rossi" o "test@test.it" mai.
- ❌ **Niente migration distruttive (`DROP TABLE`)** senza explicit
  approval umana per ogni revision. `downgrade` deve essere
  reversibile.
- ❌ **Niente face recognition cloud** — quella che c'è è già
  on-device (face-api.js client-side) e LifeOps si limita a leggere
  il risultato già esistente.

---

## 15. Roadmap in 3 milestone

Ogni milestone è mergeable, deployable, con criteri di accettazione
verificabili.

### 15.1 M1 — Foundations + Reminders + Lists MVP

**Scope:**

- Modelli `lifeops_lists`, `lifeops_list_items`,
  `lifeops_pending_approvals`
- Eventuale estensione `reminders` per `source`, `urgent`,
  `delivery_context`
- API `/lifeops/lists/*` + `/lifeops/reminders/from-intent`
- Migration Alembic + seed liste default + backfill ShoppingItem (se
  scelto in §2.2)
- Router intent NLU per `reminder | list_add | list_query |
  list_done` (no finance/notes ancora)
- Celery `lifeops.reminders.scan_due` + `materialize_rrule`
- Delivery context-aware versione base (channel selection senza
  face recognition integration ancora — placeholder che ritorna
  `push` + `voice`)
- Frontend `/lifeops/lists/*` + `ListItemRow` + `QuickAddInput`
- Pending approval flow base (creazione + decisione)
- Test: 30 frasi golden intent, pytest endpoints, vitest
  ListItemRow, smoke Playwright

**Criteri di accettazione:**

- [ ] Utente Antonio dice "ricordami di chiamare il medico domani
  alle 16" → reminder creato, notifica push fires.
- [ ] Utente Antonio dice "aggiungi pane alla spesa" → item nella
  lista `shopping` di famiglia.
- [ ] Sara (child) dice "aggiungi caramelle alla spesa" → item
  creato con `pending_approval=true`, push a Marina (parent).
- [ ] Marina dalla UI approva → item visibile a tutti.
- [ ] Pytest: 100% green; tsc strict: 0 errori.
- [ ] Migration applicata, reversibile.

**Tag finale:** `lifeops-m1`.

### 15.2 M2 — Notes + Finance MVP + delivery context-aware

**Scope:**

- Modelli `lifeops_accounts`, `lifeops_finance_categories`,
  `lifeops_transactions`
- Estensione `notes` per `tags`, `scope`, `embedding` + pipeline
  Celery embedding
- API `/lifeops/finance/*` complete (accounts, categories,
  transactions con state pending/confirmed/rejected)
- API `/lifeops/notes/search` semantica
- Router intent estensione: `note_add | note_search |
  transaction_add | finance_query`
- TransactionConfirmCard frontend + flow conferma esplicita
- Delivery context-aware completo: integrazione con face_recognition
  + presence service esistente → channel selection real-world
- Modalità sfogo/silent: queue notifiche, decode quando torna
  `normal`
- Test: golden frasi finance/notes, vitest TransactionConfirmCard,
  smoke Playwright finance flow

**Criteri di accettazione:**

- [ ] "Ho speso 12 euro in farmacia" → transaction `pending`, card
  conferma su schermo della stanza dove Antonio è riconosciuto.
- [ ] Antonio conferma → balance Contanti aggiornato.
- [ ] "Scrivimi che lunedì ho la visita medica" → nota creata con
  tag auto `medico`, ricerca semantica "visite mediche prossime" la
  trova.
- [ ] "CARA, lasciami in pace per un'ora" → modalità silent, push
  reminders ordinari accodati, urgenti (es. medicine) passano.
- [ ] Pytest: 100% green; coverage backend lifeops ≥ 80%.

**Tag finale:** `lifeops-m2`.

### 15.3 M3 — Routines fusion + UI completa + import/export

**Scope:**

- Routines famiglia come reminder ricorrenti multimediali con
  `actions` JSON (TTS + playback + face emotion + screen target)
- Import CSV bancario (dry-run + commit) — parser per i formati più
  comuni delle banche italiane (CSV Unicredit, Intesa, N26, Revolut)
- Export CSV commercialista (formato compatibile con i principali
  software)
- FinanceCharts complete (pie, bar mensile, trend annuale)
- Riepiloghi finance via voice ("quanto ho speso in farmacia questo
  mese?")
- Pending approval expiration auto-`expired` task notturno
- Audit log viewer in `/me/audit` (estendi pagina esistente se c'è)
- Performance pass: budget bundle frontend < 250KB gz per route,
  query DB < 100ms p95
- Documentazione utente in `docs/lifeops-user-guide.md` (italiano)

**Criteri di accettazione:**

- [ ] Routine "ogni mattina alle 7 svegliamo Sara" eseguita:
  TTS "Buongiorno Sara", emotion happy_warm, schermo camera_sara
  con "Oggi: scuola, allenamento alle 18".
- [ ] Import CSV Unicredit di 50 transazioni → preview dry-run con
  categorie auto-classificate → commit → balance ricalcolato.
- [ ] "Quanto ho speso in farmacia questo mese?" → risposta voce
  con totale + numero transazioni + chart push sullo schermo.
- [ ] Pending approval di 48h fa → auto-`expired`, audit log
  presente.
- [ ] Lighthouse mobile score: PWA 95+, perf 85+.

**Tag finale:** `lifeops-m3`. Merge in main + release notes.

---

## 16. Criteri di accettazione per merge

Ogni PR per `feature/lifeops` deve avere:

- [ ] `npm run typecheck` verde (frontend)
- [ ] `mypy --strict` verde (backend)
- [ ] `pytest backend/tests/` verde
- [ ] `vitest run frontend-v2/src` verde
- [ ] `npm run lint` verde (no warning)
- [ ] Almeno una smoke E2E Playwright verde per la feature toccata
- [ ] Commit messages convenzionali
- [ ] PR description con: cosa, perché, come testare, screenshot UI
  se rilevante
- [ ] CHANGELOG.md aggiornato sotto `## [Unreleased]` con la voce
  `### Added — Lifeops M{n}`
- [ ] CLAUDE.md aggiornato se il modulo aggiunge nuovi container /
  endpoint / convenzioni che impattano altri sviluppi

---

## 17. Appendice — esempi golden per il router intent

Riferimento minimo (espandi con altre 20+ frasi nel file test):

1. `"ricordami tra venti minuti di controllare il forno"` →
   `ReminderIntent(title="Controllare il forno", fires_at=<now+20m
   UTC>, urgent=false)`
2. `"il primo del mese ricordami la rata del mutuo"` →
   `ReminderIntent(title="Rata mutuo", rrule="FREQ=MONTHLY;BYMONTHDAY=1")`
3. `"aggiungi due chili di pomodori alla spesa"` →
   `ListAddIntent(list_slug="shopping", item="Pomodori", qty=2, unit="kg")`
4. `"cosa devo comprare?"` → `ListQueryIntent(list_slug="shopping")`
5. `"ho preso il pane"` → `ListDoneIntent(list_slug="shopping",
   item_substring="pane")`
6. `"scrivimi un appunto: lunedì ho la riunione alle 10"` →
   `NoteAddIntent(body="Lunedì ho la riunione alle 10", tags=["riunione"])`
7. `"trova le mie note sui medici"` → `NoteSearchIntent(query="medici")`
8. `"ho speso 12 euro in farmacia"` →
   `TransactionAddIntent(amount=Decimal("12.00"), direction="expense",
   description="Farmacia", category_slug="salute")`
9. `"mi sono entrati 1500 euro di stipendio"` →
   `TransactionAddIntent(amount=Decimal("1500.00"), direction="income",
   category_slug="stipendio")`
10. `"quanto ho speso in spesa a maggio?"` →
    `FinanceQueryIntent(metric="sum", direction="expense",
    category_slug="spesa", from_hint="maggio", to_hint="maggio")`
11. `"che tempo fa?"` → `UnsureIntent(reason="meteo, fuori dominio",
    suggested_clarification="Per il meteo dimmi 'che tempo fa oggi'.")`
12. `"raccontami una storia"` → `UnsureIntent(reason="storytelling,
    fuori dominio")`

---

## 18. Promemoria finali per l'agent

- **Verifica nel repo prima di assumere.** Se trovi un servizio
  esistente che fa l'80% di quello che ti serve, estendi non
  duplicare.
- **Italiano per gli utenti, inglese per i commenti tecnici** —
  convenzione del repo.
- **Niente codice prima della §2 (riepilogo + 5 decisioni +
  struttura).**
- **Una milestone alla volta.** Non iniziare M2 finché M1 non è
  merged + tag.
- **Privacy non è un add-on, è il fondamento.** Se ti accorgi a metà
  che stai loggando un campo sensibile, ferma e refactor.
- **Test prima del refactor finale.** Tests verdi su M{n} sono il
  gate per M{n+1}.
- **Documentation matters.** CHANGELOG + CLAUDE.md + commenti
  docstring + 1 PR description chiara per ogni milestone.

Buon lavoro.

---

*Fine prompt CARA `lifeops`.*
