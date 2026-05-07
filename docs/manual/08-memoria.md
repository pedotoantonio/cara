# Cap 8 — Memoria

> *Sintesi 30 secondi.* CARA ricorda due cose: cosa è successo (memoria
> episodica — eventi e turni chat) e cosa è vero (memoria semantica —
> fatti come allergie, preferenze, abitudini). La memoria episodica
> alimenta l'analisi a posteriori; la memoria semantica viene iniettata
> nel prompt LLM per personalizzare le risposte.

## 8.1 Due tipi di memoria

| | Episodica | Semantica |
|---|---|---|
| **Cosa contiene** | Eventi puntuali nel tempo | Fatti durevoli |
| **Esempi** | "Antonio ha aperto chat alle 14:32, è caduto router miss" | "Antonio è allergico ai pomodori" |
| **Tabella DB** | `events` | `facts` |
| **Volume** | Cresce a ~500 row/giorno | Cresce a ~5 row/giorno |
| **Usata da** | Reflective batch, audit, debug | Iniezione nel prompt LLM |
| **Retention** | 90 giorni (auto-purge) | Indefinito (manualmente cancellabile) |

## 8.2 Memoria episodica — `cara.learning.episodic`

**Modulo**: `cara/learning/episodic.py`.

Gli eventi sono record append-only con questa struttura:

```python
class Event:
    id: BigInt
    ts: datetime          # quando
    user_id: int | None   # chi (nullable per eventi system)
    kind: str             # tipo (puntato): "chat.turn", "router.miss", ...
    payload: dict          # dati arbitrari (JSONB)
    outcome: str          # "ok" / "error" / null
    duration_ms: int | None
    ref_id: str | None     # link soft a entità esterna (conversation_id, ecc.)
```

**Kinds standard**:

| Kind | Quando | Payload |
|---|---|---|
| `chat.turn` | Ogni turno chat completato | tokens, ttft, kv_cache_path |
| `router.skill_hit` | Skill ha matchato | skill, slots, tier, confidence |
| `router.intent_hit` | Tier-1 ha matchato | intent kind, args |
| `router.miss` | Tutti i tier hanno fallito → LLM | message (truncated 300) |
| `router.stage` | Per-stage telemetry pipeline | stage_name, hit/miss, duration |
| `ha.state_changed` | Subscriber HA WS riceve evento | entity_id, old, new |
| `chat.regenerated` | Utente clicca "rigenera" | conversation_id |
| `setup.step.<n>` | Step wizard salvato | settings updates |

### Scrittura — fire-and-forget

```python
from cara.learning import episodic

await episodic.record_async(
    kind="chat.turn",
    user_id=user.id,
    outcome="ok",
    duration_ms=int(elapsed * 1000),
    ref_id=conversation_id_str,
    payload={"tokens": 42, "first_token_seconds": 1.8},
)
```

`record_async()` apre la sua sessione, swallow degli errori (la chat
non deve fallire se la scrittura del log fallisce), zero block sul
chiamante.

### Lettura — query

```python
events = await episodic.query(
    session,
    user_id=42,
    kinds=("chat.turn", "router.miss"),
    since=datetime.now(timezone.utc) - timedelta(days=7),
    limit=500,
)
```

### Cleanup

`episodic.cleanup_old(session, retention_days=90)` cancella gli
eventi più vecchi di 90 giorni. Il job di pulizia gira nel
maintenance task (cap 24).

> **🔒 Sicurezza** — il `payload` è JSONB libero. **Non** scrivere
> mai password, token, contenuti email completi. La regola: payload =
> metadati per debug + analisi, non i dati utente sensibili.

## 8.3 Memoria semantica — `cara.learning.semantic`

**Modulo**: `cara/learning/semantic.py`.

I fact sono affermazioni durevoli su un utente (o sulla famiglia
intera). Ogni fact ha:

```python
class Fact:
    id: int
    user_id: int | None     # NULL = family-wide
    type: str               # "preference"|"allergy"|"habit"|"relation"|"schedule"|"personal"|"medical"
    text: str               # "È allergico ai pomodori"
    source: str             # "explicit"|"pattern"|"inferred"|"pin"
    confidence: float       # 0.0..1.0
    embedding: list[float]   # 384-dim, JSONB
    first_seen: datetime
    last_confirmed: datetime
    expiry: datetime | None
    active: bool            # soft-delete
```

### 8.3.1 Estrazione automatica

`detect_facts(message)` applica 7 pattern regex italiani al messaggio
utente, estrae candidati:

| Pattern | Esempio match | Tipo |
|---|---|---|
| Esplicito ("ricorda che...") | "ricorda che ho la riunione il lunedì" | inferito |
| Allergia 1° persona | "sono allergico ai pomodori" | allergy |
| Allergia 3° persona | "Marco è allergico al latte" | allergy (Marco) |
| Preferenza positiva | "mi piace il caffè" | preference |
| Preferenza negativa | "non mi piace lo zucchero" | preference (neg) |
| Abitudine settimanale | "ogni lunedì vado in palestra" | habit |
| Schedule | "lunedì alle 18 ho terapia" | schedule |

Esempio:

```python
from cara.learning.semantic import detect_facts, save_facts_from_message

# Detecta
candidates = detect_facts("sono allergico ai pomodori")
# [(type='allergy', text='È allergico a pomodori', confidence=0.9, source='explicit')]

# Detecta + salva con embedding (se embedder presente)
async def on_user_message(session, user_id, message, embedder):
    saved = await save_facts_from_message(
        session, user_id=user_id, message=message,
        embedder=embedder,
    )
    # Ritorna lista di Fact appena persistiti
```

### 8.3.2 Pin manuale

L'utente può aggiungere un fact a mano via `/me/memoria`:

```
POST /api/v1/memory/facts
{
  "type": "preference",
  "text": "Antonio preferisce il caffè senza zucchero",
  "source": "pin",
  "confidence": 1.0
}
```

Source `pin` indica che è stato pinned esplicitamente — non si
auto-cancella mai.

### 8.3.3 Retrieval — top-k semantico

Quando arriva un messaggio chat, il backend fa un retrieval top-k:

```python
from cara.learning.semantic import top_k_for_query

facts = await top_k_for_query(
    session,
    query=message,
    user_id=user_id,
    embedder=embedder,
    k=5,
    min_score=0.5,
)
# Lista di max 5 fact con cosine score >= 0.5
```

I fact ritornati vengono iniettati nel system prompt come "Fatti su
questo utente:" così il modello li tiene presenti.

**Importante**: il retrieval considera anche fact **family-wide** (con
`user_id IS NULL`). Cosi "siamo vegetariani" appare a tutti i membri.

### 8.3.4 GDPR — export e purge

L'utente è proprietario dei suoi fact. Due endpoint:

```
GET /api/v1/memory/export
# JSON dump completo dei fact dell'utente

DELETE /api/v1/memory/purge
# Hard-delete di TUTTI i fact dell'utente (irreversibile)
```

Per l'admin che gestisce account altrui, c'è un mirror sotto
`/admin/memory/<user_id>/...`.

> **⚠️ Attenzione** — `purge` è hard-delete (no soft). Una volta
> chiamato, niente backup automatico. Se vuoi solo "dimenticare" un
> fact, usa `PATCH /memory/facts/{id}` con `active=false` (soft-delete).

## 8.4 UI — `/me/memoria`

Pagina utente in `frontend/src/routes/MemoryPage.tsx`. Permette di:

- Vedere la lista dei fact (con filtro per tipo)
- Aggiungere a mano (form con tipo, testo, confidence)
- Cancellare (soft-delete)
- Riconfermare (bumpa `last_confirmed`, prevenendo expiry)
- Esportare (download JSON)
- Purgare tutto (con conferma double-click)

L'admin ha la versione cross-user in `/admin/memory`:
`AdminMemoryPage.tsx` mostra la roster con counts e permette di
ispezionare i fact di altri membri (utile per debug).

## 8.5 Integrazione col chat

Il flow chat con memoria semantica:

```
1. user message arriva
2. detect_facts(message) → eventuali candidati estratti
3. save_facts_from_message() → persisti con embedding
4. top_k_for_query(message) → recupera 5 fact rilevanti
5. inietta nel system prompt: "Fatti su questo utente:\n- ..."
6. genera con LLM
```

Step 2-3 e step 4 sono **paralleli all'inferenza** quando possibile
(via asyncio.gather), così la latenza non aumenta.

## 8.6 Habit detection — pattern ricorrenti

**Modulo**: `cara/learning/habits.py`. Analizza gli `events` per
trovare pattern ricorrenti settimanali.

Esempio: "Antonio aggiunge sempre 'pasta' alla spesa il lunedì"
emerge se:

- Almeno 3 occorrenze di `(user=antonio, kind=shopping.added,
  payload.title='pasta', weekday=monday, hour_bucket=morning)` in 30
  giorni

`HabitCandidate` viene scritto in `habit_candidates`. L'admin può
review e accettarli/rifiutarli da `/admin/habits` (UI futura, REST
già pronta).

```python
from cara.learning.habits import detect_and_persist

result = await detect_and_persist(
    session,
    lookback_days=30,
    min_occurrences=3,
)
# {"inserted": 5, "updated": 2}
```

Job batch settimanale (manuale o futuro Celery beat).

## 8.7 Reflective batch — cluster di miss e failure

**Modulo**: `cara/learning/reflective.py`. Analizza gli eventi
`router.miss` e `tool_call_metrics` per trovare cluster di problemi
ricorrenti.

```python
from cara.learning.reflective import run_weekly

report = await run_weekly(session, embedder, since=week_ago)
# ReflectiveReport con:
# - miss_clusters: gruppi di messaggi simili che fanno fallire il routing
# - failure_clusters: gruppi di tool-call fail per error_class
```

Esempio output:

```
miss_clusters:
  - 14 messaggi simili "ricordami di X tra Y giorni"
    suggested_pattern: r"ricordami\s+di\s+(.+)\s+tra\s+(\d+)\s+giorni"
  - 8 messaggi "qual è il numero di...?"

failure_clusters:
  - error_class=typo_prefix, count=24, tools=[add_task, list_tasks]
```

L'admin usa il report per:
- Aggiungere intent regex hardcoded per i miss ricorrenti
- Investigare il typo_prefix (probabile model variance — fix con LoRA)

## 8.8 Tool call metrics — funnel a 4 gate

**Modulo**: `cara/learning/tool_metrics.py`.

Quando il modello produce `[TOOL: add_task ...]`, il parser frontend
attraversa 4 gate:

```
1. parse_ok       → la sintassi è leggibile?
2. name_match     → il nome esiste nel registry?
3. args_valid     → gli args matchano lo schema?
4. executed       → la chiamata è andata a buon fine?
```

Ogni tentativo viene registrato con `record_attempt`:

```python
from cara.learning.tool_metrics import record_attempt_async

await record_attempt_async(
    parse_ok=True, name_match=True, args_valid=False, executed=False,
    tool_name="add_task",
    error_class=ERROR_MISSING_ARG,
    raw_call="[TOOL: add_task]",  # truncato a 500 char
    user_id=user.id,
)
```

`error_class` è uno dei 7 slug canonici:
- `typo_prefix` (es. `[TUTOOL:` invece di `[TOOL:`)
- `malformed`
- `unknown_tool`
- `missing_arg`
- `schema_invalid`
- `permission_denied`
- `exec_exception`

L'admin vede il funnel in `/admin/tool-metrics/stats` (vedi cap 20).

## 8.9 Estendere — aggiungere un nuovo pattern di estrazione fact

Editi `cara/learning/semantic.py` e aggiungi un nuovo regex in
`_DETECTOR_PATTERNS`:

```python
_DETECTOR_PATTERNS = [
    # ... esistenti ...
    {
        "kind": "schedule",
        "pattern": re.compile(
            r"\b(ho|abbiamo)\s+(\w+(?:\s+\w+)*?)\s+il\s+(lunedì|martedì|...)\b",
            re.IGNORECASE,
        ),
        "build_text": lambda m, msg: f"Ha {m.group(2)} il {m.group(3)}",
        "confidence": 0.7,
        "source": "inferred",
    },
]
```

Aggiungi un test in `tests/unit/test_semantic.py` per verificare che
il pattern matchi il caso giusto e NON matchi i falsi positivi.

---

[← Cap 7 Voce, TTS, STT](07-voce-tts-stt.md) · [README](README.md) · [Cap 9 Skill Factory →](09-skill-factory.md)
