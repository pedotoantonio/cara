# LifeOps M1 — Decisioni di design + riepilogo

> Risposta del coding agent al §2 del prompt
> `docs/CARA_Prompt_Modulo_LifeOps.md`, prima di scrivere codice.

## Riepilogo contestuale

**Cosa esiste già nel repo CARA**:
- `users` (con ruoli `parent|teen|child|elder|guest` + `is_admin`,
  `tone_preference`). NON c'è ancora `families` come tabella separata
  né `is_supervisor` boolean.
- `Reminder` v1 esistente per i 18 template "Vita Quotidiana"
  italiani con migration `e7a9c2b5d301` (campi: title, due_at,
  category, recurrence, lead_times, channels, status, etc.). Non
  ha `source`, `urgent`, `delivery_context`.
- `Task`, `Note`, `ShoppingItem` esistono separati.
- `audit_log`, `family_bus` (Redis pub/sub), `notify` service
  esistenti — riusiamo, non duplichiamo.
- Celery 4 worker code: mail/files/learn/watchdog. Aggiungeremo
  `lifeops` come 5ª.
- `proactivity_scheduler` running in-process backend.

**Cosa M1 introduce**:
- Modelli `lifeops_lists`, `lifeops_list_items`,
  `lifeops_pending_approvals` (NUOVE tabelle).
- Estensione `Reminder` con `source`, `urgent`, `delivery_context`.
- Aggiunta `users.is_supervisor` boolean.
- API REST `/api/v1/lifeops/lists/*` + `/lifeops/pending/*`.
- Router intent NLU (4 intent kind: reminder, list_add, list_query,
  list_done) — implementato come stub Tier-0 regex in M1, NLU full
  rimandato a M1.5 quando l'LLM HTTP separation è disponibile.

**Branch**: `feature/top5-bootstrap` (bootstrap di tutte le 5 top
features in parallelo, mergeable individualmente).

## 5 decisioni — scelte prese

### 1. Reminder fusion: ESTENDO il modello esistente

Aggiungo 3 colonne via Alembic migration ALTER TABLE: `source`,
`urgent`, `delivery_context`. Il vecchio scheduler scan_due esistente
gestisce sia template-derived che conversational-derived reminders —
la logica differente è sul render del template form (frontend) e sul
dispatcher delle azioni multimediali (lifeops.delivery in M2/M3).

**Razionale**: zero duplicazione, 100% backward compat con i 18
template italiani che già funzionano, niente migrazione dati.

### 2. Shopping fusion: nuovo `lifeops_lists` + backfill

Creo tabelle `lifeops_lists` + `lifeops_list_items` separate. Migration
di backfill (in M1) crea una `List` con `slug='shopping'`,
`scope='family'` per ogni famiglia esistente e ne popola gli items
da `shopping_items`. `ShoppingItem` resta in DB ma deprecato — il
codice nuovo legge solo da `lifeops_lists`. Hard delete della tabella
`shopping_items` rimandato a M2 dopo verifica produzione.

**Razionale**: ShoppingItem è un caso particolare di una lista —
modellarlo separatamente è debt. Migration backfill conserva i dati.

### 3. Categorie finance: 12 globali seedate per famiglia (non
   ereditate da template)

Per M2 (finance non in M1). Ogni famiglia ha le sue 12 categorie
seedate al primo accesso al modulo finance. Famiglia può aggiungere
custom successivamente (campo `is_system=false`). Non rinegoziato.

**Razionale**: il prompt LifeOps ha già la lista finale, non la
rinegozio.

### 4. Conferma transactions: bloccante in UI (no chat)

Per M2 (finance non in M1). La conferma transaction è un'azione UI:
card a tutto schermo o sheet bottom con campi pre-compilati +
bottoni `[Confermo]` `[Modifica]` `[Annulla]`. La chat può mostrare
il link "vai a conferma" inline ma non accetta "sì confermo" via
testo (troppo facile farsi fregare da Whisper).

**Razionale**: testo via voice è ambiguo, UI è esplicita.

### 5. Pending approval supervisor: flag `users.is_supervisor` nuovo

Migration M1 aggiunge `is_supervisor: Boolean` su `users`, default
`True` per `role='parent'`, `False` per gli altri (backfill via
SQL). Pending approval notifica al primo `is_supervisor=true` della
"famiglia" (per ora: tutti gli user attivi, single-family stack).

**Razionale**: più flessibile di hard-coded "primo parent" e
preparato per multi-family futuro.

## Single-family vs multi-family

**Decisione esplicita non in §2**: per M1 lavoriamo in modalità
**single-family stack**. Tutti gli user attivi sono nella stessa
famiglia. Non aggiungo tabella `families` ora. `scope='family'`
significa "visibile a tutti gli user attivi del backend".

Multi-family (più famiglie su un'istanza CARA) è roadmap futura
quando un singolo NanoPC servirà più nuclei familiari (caso d'uso
attualmente nullo).

## Struttura file proposta

```
backend/cara/
├── lifeops/
│   ├── __init__.py
│   ├── intents.py            # Pydantic Intent classes (subset M1)
│   ├── intent_router.py      # Tier-0 regex M1, LLM full in M1.5
│   ├── prompts.py            # System prompts router
│   └── dispatchers/
│       ├── __init__.py
│       ├── reminders.py      # reminder_from_intent → DB write
│       └── lists.py          # list_* → DB write
├── models/
│   └── lifeops_list.py       # List + ListItem + PendingApproval
└── api/v1/
    └── lifeops_lists.py      # /lifeops/lists/* + /lifeops/pending/*

backend/alembic/versions/
└── c1f8a5d3e926_lifeops_m1.py   # tabelle + ALTER reminders + is_supervisor

backend/tests/unit/
└── test_lifeops_lists.py     # smoke CRUD

frontend-v2/src/
├── api/
│   └── lifeopsLists.ts
└── routes/lifeops/
    └── ListsPage.tsx          # listing + create + drill
```

## Cose RIMANDATE da M1 esplicite

- **Router intent NLU completo** (LLM function calling) — M1.5 dopo
  Ondata δ LLM HTTP separation. M1 ha solo Tier-0 regex (pattern
  `aggiungi X alla spesa`, `ricordami di Y domani alle Z`).
- **Finance** (Account, Category, Transaction) — M2.
- **Routine famiglia multimediali** (actions JSON) — M3.
- **Frontend UI completa** — M1 ha solo `/lifeops/lists` minimale;
  routes finance/routines aggiunte in M2/M3.

## Criteri di accettazione M1 (rinforzati)

- [ ] Migration applicata (forward + downgrade testato in CI).
- [ ] `users.is_supervisor` backfillato per gli user esistenti.
- [ ] Backfill ShoppingItem → lifeops_lists eseguito senza perdita
  dati.
- [ ] POST `/lifeops/lists` crea lista nuova; POST `/.../items`
  aggiunge item.
- [ ] Item creato da un `child` parte con `pending_approval=true` se
  la lista è `scope='family'`.
- [ ] `POST /pending/{id}/approve` rimuove il flag e pubblica evento
  `lifeops.pending.approved` sul family-bus.
- [ ] Pytest smoke verde, TS strict frontend zero errori.

---

Pronto a iniziare l'implementazione su questa base.
