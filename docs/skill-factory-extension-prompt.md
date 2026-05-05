# CARA — Estensione v0.7: Skill Factory (auto-skill bootstrap)

> **Scopo del documento**: questo è un *implementation prompt* che descrive in
> modo completo (architettura, schema, prompt LLM, roadmap, test) un nuovo
> modulo della webapp CARA. L'agente che lo riceve deve implementarlo
> esattamente come scritto, leggendo `CLAUDE.md` per il contesto del codebase
> esistente, e fermandosi a chiedere conferma SOLO sulle decisioni esplicitamente
> marcate "[DECISIONE]".

## 1. Sommario esecutivo

CARA oggi gestisce un set finito di intent (chat, todo, spesa, note, news,
radio, who_is_home, discover, file upload, recipe_chain). Ogni nuova capacità
richiede:
1. Un modulo Python dedicato (`cara/services/<x>.py`)
2. Una intent regex hard-coded (`recipe_chain._INTENT_RE`, `intent_router.py`, ecc.)
3. Un wiring in `chat.py`
4. Un rebuild del backend

**Risultato**: ogni richiesta utente fuori-script viene servita male (1.5B che
prende parole letteralmente, vedi Step 65). E aggiungere capacità è O(numero di
intent) lavoro umano.

**Idea**: una **Skill Factory**. Quando arriva un intent non gestito, un
"Skill Architect" LLM progetta un piano deterministico composto da primitive
esistenti, lo esegue una volta sotto supervisione, e — se Tony approva — lo
persiste come *skill* riusabile con il suo intent matcher. Ogni interazione
fallita arricchisce il sistema; non servono più rebuild per ogni caso d'uso.

Ispirazione: AutoGen / Voyager / OpenAI Plugins meta-discovery / Anthropic
"Computer Use" skill memory. Adattato al vincolo di un 1.5B locale + cloud LLM
opt-in per il solo authoring.

## 2. Filosofia e principi

1. **Determinismo a runtime**: una skill in produzione esegue un piano JSON
   validato. Niente eval, niente shell, niente codice generato. Solo
   composizione di primitive registrate.
2. **LLM dove conta**: il 1.5B fa solo il dispatcher di intent (Tier-3) e la
   conversazione. L'authoring di una nuova skill richiede capacità di
   ragionamento e produzione JSON strutturato — quello va al cloud LLM (Claude
   Haiku o equivalente, opt-in admin).
3. **Approvazione umana**: nessuna skill auto-generata diventa "live" senza
   un OK esplicito di Tony. Audit completo di chi ha approvato cosa quando.
4. **Reversibilità**: ogni skill è versionata. Disattivare/eliminare una skill
   non distrugge dati storici; lascia solo intent senza match.
5. **Migrabilità**: le intent hard-coded esistenti (`recipe_chain`,
   `intent_router`) vengono migrate come skill seed nella Fase F. Niente
   rotture, coexistenza graduale (cfr. CDA Fase B).

## 3. Architettura — 5 componenti

### 3.1 Capability Registry

Catalogo enumerato di **primitive** (funzioni Python esistenti) e **skill**
(composizioni). Le primitive sono dichiarate via decoratore in moduli che già
esistono — non si "scoprono" automaticamente.

```python
# cara/skills/registry.py
@primitive(
    name="add_shopping",
    description="Aggiunge un articolo alla lista della spesa dell'utente.",
    args_schema={"title": "string"},
    returns_schema={"id": "uuid", "title": "string"},
)
async def _prim_add_shopping(session, user_id, title): ...
```

Tutte le primitive disponibili al boot vengono iscritte in memoria. Le
skill sono caricate da DB.

### 3.2 Intent Dispatcher (4 tier)

Sequenziale, fast-path-first:

| Tier | Tipo | Latenza | Quando |
|------|------|---------|--------|
| 1 | Exact regex match su `intent_examples` | <1 ms | Skill già seeded |
| 2 | Embedding cosine match (MiniLM, CPU) ≥ 0.78 | ~30 ms | Skill simili |
| 3 | LLM 1.5B classifier "matches_skill_id?" con shortlist top-5 di Tier-2 | 1–3 s | Disambiguazione |
| 4 | Unhandled → trigger Skill Author (asincrono, niente blocco UX) | — | Apprendimento |

Il Tier-4 NON blocca la risposta. CARA risponde all'utente "Non sono ancora
attrezzata per questo, ma mi sto preparando una skill — la rivedrai nelle
notifiche admin entro 1 minuto." E in background lancia il Skill Author.

### 3.3 Skill Author (meta-LLM call)

**Input**: messaggio utente + ultimi 3 turni + capability registry compatta.

**Output**: un JSON con `intent_examples`, `slot_extraction`, `plan`,
`response_template` — vedi schema §5.

**Modello**: cloud LLM (Anthropic Claude Sonnet 4.6 o Haiku 4.5). Setting
`skill_author_provider` (default `anthropic_haiku`), `skill_author_api_key`
(env var). Il 1.5B locale NON è in grado di produrre questo JSON in modo
affidabile.

**Costo**: ~2-5k token per call → ~$0.003 con Haiku. Trascurabile a casa.

**Privacy**: solo il messaggio utente + capability registry vanno al cloud.
Niente cronologia, niente dati di altri utenti, niente file allegati. Audit
log esplicito di ogni call.

### 3.4 Skill Compiler & Executor

**Compiler**: prende il JSON del Skill Author, valida ogni step contro lo
schema delle primitive (args, types). Rifiuta plan con primitive sconosciute,
loop, o args non templettabili.

**Executor**: esegue il plan step-by-step. Ogni step:
1. Risolve gli args templettando `{slot_name}` e `{step_id.field}` con i valori
   correnti
2. Valida gli args contro lo schema della primitiva
3. Chiama la primitiva
4. Salva l'output nel context con la key `step.id`
5. Su failure: cattura, rollback delle scritture DB nel turno corrente,
   escala all'utente con `ask_user("Si è verificato un errore in '{step.id}'.
   Vuoi riprovare o aiutarmi a capire cosa è andato storto?")`

Niente loop, niente branching condizionale all'inizio. Pipeline lineare. Se
un caso d'uso lo richiede, il Skill Author può chiedere clarificazione via
`ask_user` come step esplicito.

### 3.5 Learning Loop

Dopo l'esecuzione (success o fail) di una skill auto-authored, mostra a Tony
in `/admin` (non in chat — non blocca):

> **Nuova skill proposta**: "ricetta_to_spesa"
> Match esempi: "aggiungi gli ingredienti della torta margherita..."
> Plan: discover → extract_list → add_shopping_bulk
> Esecuzione di prova: ✅ 10 ingredienti aggiunti
> [Approva] [Modifica] [Scarta]

Approva → `status='active'`, intent_examples vanno nei dispatcher Tier-1/2.
Scarta → log, niente persistenza.

Periodicamente (job di maintenance ogni 24h):
- Dedup: skill con `plan` identico vengono unificate, intent_examples merge
- Promozione: skill con success_count > 10 e failure_rate < 5% diventano
  "trusted" (può essere il criterio per auto-approvare il prossimo simile)

## 4. Schema database

Tre tabelle nuove:

```sql
CREATE TABLE skills (
  id              UUID PRIMARY KEY,
  name            TEXT NOT NULL,                    -- snake_case, unique
  description     TEXT NOT NULL,
  intent_examples JSONB NOT NULL DEFAULT '[]',      -- list[str]
  slot_extraction JSONB NOT NULL DEFAULT '{}',      -- {slot: regex|enum|llm}
  plan            JSONB NOT NULL,                   -- see §5
  response_template TEXT,                           -- "Ho fatto X: {result}"
  status          TEXT NOT NULL DEFAULT 'pending',  -- pending|active|disabled
  created_by_user_id INT REFERENCES users(id),
  approved_by_user_id INT REFERENCES users(id),
  auto_authored   BOOLEAN NOT NULL DEFAULT TRUE,
  version         INT NOT NULL DEFAULT 1,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX skills_name_uniq ON skills(name);

CREATE TABLE skill_intent_embeddings (
  skill_id   UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
  example    TEXT NOT NULL,
  vector     VECTOR(384),                           -- pgvector ext
  PRIMARY KEY (skill_id, example)
);
CREATE INDEX skill_intent_emb_ivfflat
  ON skill_intent_embeddings USING ivfflat (vector vector_cosine_ops);

CREATE TABLE skill_runs (
  id             UUID PRIMARY KEY,
  skill_id       UUID NOT NULL REFERENCES skills(id),
  user_id        INT NOT NULL REFERENCES users(id),
  user_message   TEXT NOT NULL,
  slots          JSONB,
  step_outputs   JSONB,
  success        BOOLEAN NOT NULL,
  error          TEXT,
  duration_ms    INT NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX skill_runs_skill_id_at ON skill_runs(skill_id, created_at DESC);
```

**Dipendenza nuova**: `pgvector` extension Postgres + Python `pgvector` package
+ `sentence-transformers` (modello `paraphrase-multilingual-MiniLM-L12-v2`,
~120 MB, gira su CPU).

## 5. Schema della skill (JSON)

```json
{
  "name": "ricetta_to_spesa",
  "description": "Cerca una ricetta su internet, estrae gli ingredienti e li aggiunge alla lista della spesa.",
  "intent_examples": [
    "aggiungi gli ingredienti della torta margherita alla spesa",
    "metti gli ingredienti per il tiramisù nella lista della spesa",
    "aggiungimi nella spesa quello che serve per fare la pizza"
  ],
  "slot_extraction": {
    "dish": {
      "method": "regex",
      "pattern": "ingredient\\w+\\s+(?:di|della|del|per)\\s+(?:la|il|lo|le|i|gli)?\\s*([\\w\\s'’\\-àèéìòù]{3,80}?)\\s+(?:alla|nella|in)\\s+(?:la\\s+)?(?:lista\\s+(?:della\\s+)?)?spesa",
      "group": 1
    }
  },
  "plan": {
    "steps": [
      {
        "id": "search",
        "tool": "discover",
        "args": {
          "query": "ricetta {dish} ingredienti",
          "kind": "article"
        }
      },
      {
        "id": "extract",
        "tool": "extract_list",
        "args": {
          "text": "{search.text}",
          "what": "ingredienti",
          "filter_quantities": true,
          "max_items": 30
        }
      },
      {
        "id": "add",
        "tool": "add_shopping_bulk",
        "args": {
          "titles": "{extract.items}"
        }
      }
    ]
  },
  "response_template": "Ho cercato la ricetta di {dish} (fonte: {search.source_domain}) e ho aggiunto {add.count} ingredienti alla lista della spesa: {add.preview}.",
  "fallback_response": "Non sono riuscita a trovare/estrarre la ricetta di {dish}. Provo a cercartela in browser? {search.url}"
}
```

## 6. Il prompt di Skill Author (LLM cloud)

Il prompt deve produrre il JSON dello schema §5, niente di più. Salvato in
`cara/skills/author_prompt.py` come costante, configurabile da admin tramite
`skill_author_prompt` setting (analogo a `llm_system_prompt`).

```text
Sei "Skill Architect", un meta-agente di CARA — un assistente domestico
self-hosted per la famiglia Pedoto. Il tuo compito: progettare una "skill"
deterministica per gestire una richiesta utente che il sistema non ha ancora
imparato a fare.

OUTPUT: SOLO un singolo JSON valido conforme allo schema fornito. Nessun
testo prima/dopo, nessun markdown, nessun commento.

REGOLE:
1. Componi SOLO con primitive elencate sotto. Non inventare tool nuovi.
2. Identifica le SLOT della richiesta (es. "torta margherita" → dish:string).
   Per ogni slot definisci un metodo di estrazione: regex (preferito) o
   "llm" (solo se la slot è semantica e regex non basta).
3. Scrivi 5-8 intent_examples in italiano: 1 è il messaggio originale, gli
   altri sono parafrasi naturali (varia verbi, preposizioni, ordine).
4. Il plan è una pipeline LINEARE di step. NO loop, NO branching, NO
   condizionali. Ogni step può referenziare l'output dei precedenti via
   {step_id.field}.
5. Se la richiesta NON è risolvibile con le primitive disponibili, rispondi:
   {"unsupported": true, "reason": "<perché>", "missing_primitives": [...]}
6. response_template usa {slot} e {step.field}. Tono: caldo, breve, italiano.
7. fallback_response per quando il piano fallisce a metà.

PRIMITIVE DISPONIBILI:
[LISTA AUTO-GENERATA DAL REGISTRY, formato compatto:
"  - add_shopping(title:str) → {id, title}"
"  - discover(query:str, kind:'article'|'audio_stream'|...) → {url, title, source_domain, text, metadata}"
"  - extract_list(text:str, what:str, filter_quantities:bool, max_items:int) → {items: list[str]}"
"  - summarize(text:str, max_words:int) → {summary: str}"
"  - ask_user(question:str) → {answer: str}"
... ecc ...
]

CONTESTO:
- Utente: {user_role} ("parent" | "child" | "elder" | "guest")
- Ultimi 3 turni: {recent_turns}
- Slot già rilevate (suggerimento, raffina): {auto_detected_slots}

RICHIESTA UTENTE:
"{user_message}"

PROGETTA. SOLO IL JSON.
```

## 7. Primitive iniziali da registrare

Mappare le funzioni esistenti come primitive. Per la maggior parte è solo
metterci il decoratore. Quelle marcate **NUOVA** vanno scritte ex novo.

| Primitiva | Modulo esistente | Note |
|-----------|------------------|------|
| add_task, complete_task, list_tasks | services/tasks.py | wrap |
| add_shopping, list_shopping | services/shopping.py | wrap |
| add_shopping_bulk **NUOVA** | services/shopping.py | per `extract_list → bulk add` |
| add_note, list_notes | services/notes.py | wrap |
| get_news | services/news.py | wrap |
| play_radio, stop_radio | services/radio.py + radio player frontend | wrap (frontend-side handler) |
| who_is_home | services/family.py | wrap |
| discover | cda.discover | wrap, ritorna anche `text` da metadata |
| extract_list **NUOVA** | services/extraction.py | regex deterministica + fallback LLM (mini-prompt) |
| summarize **NUOVA** | services/extraction.py | LLM con prompt strutturato |
| ask_user **NUOVA** | api/chat.py + frontend | apre un sub-flow di clarificazione |
| speak | esistente (TTS Piper) | wrap |
| read_url **NUOVA** | services/web.py | fetch + trafilatura, no search |

## 8. Roadmap implementativa (totale: 8-10 giorni effettivi)

### Fase A — Foundations (1.5 giorni)
- Migration alembic per le 3 tabelle (`skills`, `skill_intent_embeddings`,
  `skill_runs`). Estensione pgvector da abilitare nel container.
- Modulo `cara/skills/`: `models.py`, `registry.py`, `dispatcher.py`,
  `executor.py`, `author.py` con stub.
- Decoratore `@primitive` + test che enumera le primitive disponibili.

### Fase B — Executor + primitive base (2 giorni)
- Implementare `SkillExecutor.run(skill, user_input, context)` con templating
  di slot e step outputs.
- Wrappare le primitive esistenti (vedi §7).
- Scrivere `extract_list` (regex deterministica + fallback al 1.5B con prompt
  strutturato), `add_shopping_bulk`, `read_url`.
- Test unit: eseguire una skill seedata a mano (la "ricetta_to_spesa") e
  verificare 10 ingredienti aggiunti.

### Fase C — Dispatcher Tier-1/2 (1.5 giorni)
- Embedding model load lazy. Setting `skill_intent_embedding_model` default
  `paraphrase-multilingual-MiniLM-L12-v2`.
- API: `dispatcher.match(message)` → `(skill, slots, confidence)` o `None`.
- Cache embeddings al boot (dump da DB).
- Wire in `chat.py` PRIMA del intent_router esistente. Coexistenza graduale.

### Fase D — Skill Author + cloud LLM (2 giorni)
- Provider cloud: client per Anthropic API (`anthropic` package). Setting
  `skill_author_provider` (`anthropic_haiku` / `anthropic_sonnet` / `disabled`)
  + `ANTHROPIC_API_KEY` env.
- Funzione `author_skill(message, context)` → JSON skill (con validation +
  retry su JSON invalido, max 2 retry).
- Job asincrono: quando Tier-4 trigga, spawn task background, salva skill
  con `status='pending'`. NON blocca la chat.
- Endpoint `POST /api/v1/admin/skills/{id}/approve` e `/reject`.

### Fase E — UX admin (1.5 giorni)
- Pagina `/admin/skills`: lista (active, pending, disabled), search.
- Detail page: vista del JSON, history degli skill_runs (success rate),
  bottone "Edit" che apre un editor JSON con validazione live.
- Notifica push (toast + Telegram) quando arriva una pending skill.
- Pagina `/skills` per utenti normali: lista delle skill attive con
  esempi-cliccabili che pre-popolano la chat.

### Fase F — Migrazione skill esistenti (1 giorno)
- Riscrivere come skill JSON: `recipe_chain`, gli intent del `intent_router`
  (date, list_tasks, ecc.). Salvarle in DB come seed via migration o
  bootstrap script. `auto_authored=false`, `status='active'`.
- Rimuovere progressivamente il codice hard-coded man mano che le skill
  superano in confidence.
- Tenere intent_router come fallback ultimo per N versioni (rollback).

### Fase G — Sicurezza & rate limit (mezza giornata)
- Rate limit: max 10 skill auto-author per utente al giorno (Redis bucket,
  riusa pattern Step 62).
- Per ruoli `child`/`teen`: skill auto-authored DEVONO essere approvate da
  un parent prima di essere live (anche se un altro parent l'aveva approvata
  per sé — lo scope è `created_by`).
- Audit log esteso: `skill.author.requested`, `skill.author.completed`,
  `skill.approved`, `skill.executed`, `skill.failed`.

## 9. Test di accettazione

| # | Input | Risultato atteso |
|---|-------|------------------|
| 1 | "aggiungi gli ingredienti della torta margherita alla spesa" | Match seed `ricetta_to_spesa` (Tier-1) → 10 ingredienti in <2s |
| 2 | "metti nella spesa quello che serve per fare il tiramisù" | Match Tier-2 (embedding) sulla stessa skill → ingredienti tiramisù |
| 3 | "trova un parcheggio gratuito a Ferrara stasera" | Tier-4 trigga Skill Author → admin notifica → approva → da prossima volta Tier-1 |
| 4 | "calcola la mia bolletta media degli ultimi 3 mesi" | Skill Author ritorna `unsupported` (manca primitiva `invoice_lookup`) → CARA risponde onesta |
| 5 | "ciao come stai" | NESSUN match (no intent strutturato) → fallthrough al chat normale 1.5B |
| 6 | Tony approva 5 skill, una contiene un loop nel plan | Compiler rifiuta in Fase D, mai diventa pending |
| 7 | Cloud LLM API down | Skill Author fallisce graceful, log `skill.author.provider_unavailable`, utente vede "non riesco a imparare ora, riprova" |
| 8 | Run skill, step #2 fallisce | Rollback DB del turno, `ask_user` per chiarimento, niente dati spuri |

## 10. Cosa NON è in scope (esplicito)

- **Code skills** (skill che generano Python sandboxato per logica complessa
  non esprimibile in pipeline): sarà v0.8.
- **Cross-skill composition** (skill che invoca skill): v0.8.
- **Multi-modale** (immagini/audio in pipeline): v0.8 dopo Whisper integration.
- **Self-modification** (CARA che riscrive le sue primitive): mai. Out of scope
  per principio di sicurezza.
- **Skill marketplace** tra utenti CARA: out of scope (privacy first).

## 11. Decisioni aperte (chiedere a Tony)

- **[DECISIONE 1]** Cloud LLM provider per skill authoring: Anthropic Haiku
  (~$0.003/skill) o usare il 3B locale (gratis ma lento, ~30s, qualità JSON
  inferiore)? *Raccomandazione*: Haiku, opt-in admin, limite 50/mese cap.
- **[DECISIONE 2]** Auto-approve trusted skills (success > 10, failure_rate
  < 5%) o sempre richiedere conferma manuale? *Raccomandazione*: sempre
  manuale per Step v0.7, valutare auto-approve in v0.8 dopo dati reali.
- **[DECISIONE 3]** Embedding model: `paraphrase-multilingual-MiniLM-L12-v2`
  (120 MB, italian-good) o `multilingual-e5-small` (470 MB, più preciso)?
  *Raccomandazione*: MiniLM per partire (CPU-friendly), upgrade dopo benchmark.

## 12. Definition of Done

- Tony scrive in chat un intent fuori-script
- CARA risponde "non sono ancora attrezzata, sto preparando una skill"
- Entro 60s arriva notifica admin con la proposta JSON + esecuzione di prova
- Tony clicca approva
- Tony riscrive la stessa cosa: questa volta CARA esegue al primo colpo, in <2s
- La skill compare in `/skills` con esempi cliccabili
- L'audit log mostra l'intera catena (author requested → completed → approved →
  executed)
- Nessun crash, nessun deploy, nessun rebuild

---

**Fine prompt di estensione.** L'agente che riceve questo documento implementa
le fasi A-G in ordine, completando ognuna con: rebuild dei container, test
di accettazione del corrispondente, aggiornamento di `CLAUDE.md` con un nuovo
"Step XX completato" + Telegram a Tony per notifica.
