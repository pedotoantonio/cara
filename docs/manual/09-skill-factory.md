# Cap 9 — Skill Factory

> *Sintesi 30 secondi.* Le skill sono "ricette JSON" che la chat può
> eseguire come tool deterministici. Esempio: "ricetta → spesa"
> prende un URL, estrae ingredienti, li aggiunge alla lista. Una skill
> compone primitive registrate (extract_list, summarize, add_shopping_bulk,
> ecc.) in step lineari. Si autorizzano dall'admin, si attivano via
> dispatcher Tier-1/2/3, si eseguono dall'executor.

## 9.1 Cosa è una skill

Una skill è una riga della tabella `skills` con questa shape JSON:

```json
{
  "id": "uuid",
  "name": "ricetta_to_spesa",
  "description": "Da URL ricetta → ingredienti → spesa",
  "intent_examples": [
    "voglio fare le lasagne",
    "metti gli ingredienti per la pasta in lista"
  ],
  "slot_extraction": {
    "url": {
      "method": "regex",
      "pattern": "https?://\\S+",
      "group": 0,
      "required": true
    }
  },
  "plan": {
    "steps": [
      {"id": "fetch", "tool": "read_url",
       "args": {"url": "{url}", "max_chars": 8000}},
      {"id": "extract", "tool": "extract_recipe_ingredients",
       "args": {"text": "{fetch.text}", "max_items": 30}},
      {"id": "add", "tool": "add_shopping_bulk",
       "args": {"titles": "{extract.items}"}}
    ]
  },
  "response_template": "Aggiunti {add.count} ingredienti dalla ricetta.",
  "fallback_response": "Mi spiace, non sono riuscita: {error}",
  "status": "active",
  "version": 3,
  "auto_authored": true
}
```

**Anatomia**:

- `name` — slug univoco usato per cache, log, dispatcher
- `description` — testo umano per UI admin + Skill Author cloud
- `intent_examples` — frasi tipo che attivano la skill (Tier-2 cosine
  fa l'embedding di queste)
- `slot_extraction` — regex per estrarre slot dal messaggio utente
- `plan` — sequenza di step. Ogni step chiama una primitive con args
- `response_template` — risposta finale, con interpolazione `{step_id.field}`
- `fallback_response` — testo se il piano esplode
- `status` — `pending` / `active` / `disabled`
- `version` — bumpa ad ogni edit
- `auto_authored` — `true` se generata da Skill Author cloud

## 9.2 Le primitive — il vocabolario delle skill

Una skill può chiamare solo le primitive registrate. CARA ne ha 7
built-in:

| Primitive | Cosa fa |
|---|---|
| `discover` | Cerca su web (CDA), ritorna URL+titolo+text |
| `extract_recipe_ingredients` | Regex IT su sezione "Ingredienti" |
| `add_shopping_bulk` | Aggiunge lista titoli alla spesa utente |
| `extract_list` | List parser generico (bullet/numerati/CSV) |
| `summarize` | Estrattivo TF-IDF top-N frasi |
| `ask_user` | Marker "needs input" — la skill ferma e chiede |
| `read_url` | HTTP GET + trafilatura → {text, title, source_domain} |

Le ultime quattro sono la **Phase B** generica (cap 9.4).

### Aggiungere una primitive

Edita `backend/cara/skills/primitives.py` (o crea un nuovo file
sub-modulo e importalo da lì):

```python
from cara.skills.registry import primitive

@primitive(
    name="conta_parole",
    description="Conta le parole in un testo.",
    args_schema={"text": "string"},
    returns_schema={"count": "int"},
    needs_session=False,
    needs_user_id=False,
)
async def _prim_conta_parole(text: str) -> dict:
    return {"count": len(text.split())}
```

Restart backend → la primitive è disponibile per tutte le skill.

**Convenzione signature**:
- Sempre `async def`
- Ritorno **deve essere un dict** (le sue chiavi sono i `field` per
  `{step.field}`)
- Se `needs_session=True`, primo arg posizionale è `session`
- Se `needs_user_id=True`, secondo arg posizionale è `user_id`
- I successivi sono kwargs (validati via Pydantic prima)

> **🔒 Sicurezza** — non scrivere primitive che fanno `eval()` o
> `subprocess.run()` di stringhe utente. Il modello LLM può infilarci
> di tutto. Se hai bisogno di code execution, isola in container con
> rete bloccata.

## 9.3 Executor — come si esegue un piano

**File**: `cara/skills/executor.py`.

### Step di esecuzione

Il piano è una lista di step. Ognuno produce un dict di output che
diventa accessibile come `{step_id.field}` agli step successivi.

```python
from cara.skills.executor import run

context = await run(
    session, skill=skill, user_id=42, slots={"url": "https://..."}
)
# context = {
#   "url": "https://...",                       # da slots
#   "fetch": {"text": "...", "title": "...", ...},  # output step "fetch"
#   "extract": {"items": [...], "count": 12},      # output step "extract"
#   "add": {"count": 12, "preview": "..."}          # output step "add"
# }
```

### Resolution di `{ref}`

Stringhe negli `args` come `"{fetch.text}"` o `"{slot_name}"` vengono
risolte ricorsivamente (anche dentro liste e dict annidati).

Caso speciale: se la stringa **è solo** un riferimento (es. `"{extract.items}"`),
il valore viene preservato col tipo originale (lista, non rappresentazione
testuale).

### Fallimenti

`SkillExecutionError` viene sollevata se uno step fallisce. Il chat
layer la cattura e renderizza `fallback_response` invece di `response_template`.

```python
try:
    ctx = await run(session, skill=sk, user_id=user.id, slots=slots)
    summary = render_response(sk, ctx)
except SkillExecutionError as exc:
    summary = render_fallback(sk, dict(slots), str(exc.cause))
```

L'errore viene anche loggato come `chat.skill_run_failed` (episodic).

## 9.4 Phase B — primitive generiche

Le 4 primitive di Phase B sono pensate per essere **componibili** senza
scrivere Python:

### `extract_list`

Parser di liste da testo libero.

```json
{"id": "items", "tool": "extract_list", "args": {
  "text": "{notes.body}",
  "hint": "spesa",
  "max_items": 30
}}
```

Riconosce:
- Bullet: `-`, `*`, `•`, `‣`, `→`
- Numerati: `1.`, `1)`, `(1)`, `01.`
- Sezione con header: cerca riga "Spesa:" o "Lista:" e prende dopo
- Fallback CSV: se nessun bullet, splitta per virgola/newline

### `summarize`

Estratto top-N frasi:

```json
{"id": "tldr", "tool": "summarize", "args": {
  "text": "{article.text}", "max_sentences": 3
}}
```

Ritorna `{summary: "...", sentence_count: 3}`.

### `ask_user`

Marker per fermare il piano e chiedere clarificazione:

```json
{"id": "ask", "tool": "ask_user", "args": {
  "prompt": "Quale lista vuoi aggiornare?",
  "choices": ["Spesa", "Cose da fare", "Idee"]
}},
"response_template": "{ask.prompt}\n{ask.choices_text}"
```

L'executor non si ferma davvero — ritorna il marker e il
`response_template` lo renderizza. Lo step successivo del piano viene
comunque eseguito (di solito non ce n'è perché il pattern è
l'ultimo).

### `read_url`

```json
{"id": "fetch", "tool": "read_url", "args": {
  "url": "{user_url}", "max_chars": 5000
}}
```

Ritorna `{text, title, source_domain, fetched_ok, error}`. Su
fallimento di rete, `fetched_ok=false` invece di sollevare — la skill
può decidere se procedere o fallire.

## 9.5 Dispatcher — Tier-1/2/3

**File**: `cara/skills/dispatcher.py`.

Quando arriva un messaggio chat, il dispatcher prova tre livelli in
sequenza fino al primo match.

### Tier-1 — regex deterministico

Per ogni skill attiva, applica lo `slot_extraction.<slot>.pattern` al
messaggio. Se TUTTI gli slot required matchano → hit.

Veloce (~5ms), zero-cost, deterministico. Buono per intent rigidi
("aggiungi X alla spesa", "ricordami di Y entro Z").

### Tier-2 — cosine sui intent_examples

Encode il messaggio + tutti gli `intent_examples` di tutte le skill
attive. Ritorna la skill con la maggior cosine similarity, se >=
threshold (default 0.65).

~50ms (con cache embedding warm). Buono per intent fuzzy ("voglio
fare le lasagne", "cosa serve per la pasta").

**Configurazione**:
- `skill_dispatcher_tier2_enabled` — master switch
- `skill_dispatcher_tier2_threshold` — soglia cosine

### Tier-3 — LLM classifier

Costruisce un prompt: "Hai queste skill: 1. X 2. Y 3. Z. Utente ha
detto: «...». Rispondi con il numero o 0 se nessuna."

Il modello locale 1.5B risponde con un numero.

500ms-2s, opt-in. Off di default (`skill_dispatcher_tier3_enabled=false`).
Abilitalo solo se ti fidi del modello e vuoi flessibilità massima.

### Pattern del codice

```python
from cara.skills.dispatcher import match_with_tier

result = await match_with_tier(
    session, message,
    embedder=embedder,
    llm_call=llm_call,
    tier2_enabled=True,
    tier3_enabled=False,
    tier2_threshold=0.65,
)
if result is None:
    # nessun match — il chat fa fallthrough al LLM normale
    return None

skill, slots, tier_name, confidence = result
# tier_name: "tier1" | "tier2" | "tier3"
# confidence: 1.0 per tier1/3, cosine score per tier2
```

### Cache

Tier-2 mantiene un index in-memory: `{skill_id: (skill, [intent_embeddings])}`.
Costruito lazy, invalidato a ogni CRUD su skill (via
`skill_dispatcher.invalidate_cache()`).

## 9.6 Skill Author — generazione automatica via cloud

**File**: `cara/skills/author.py`.

**Flow**:

1. Utente dice qualcosa che non matcha nessuna skill (router miss).
2. Admin (o auto-trigger) chiama `POST /admin/skills/author` con il
   messaggio utente.
3. Skill Author manda il messaggio + il catalogo di primitive ad
   Anthropic Haiku con un system prompt che dice "scrivi una skill JSON
   che soddisfi questa intent".
4. Haiku ritorna un JSON skill candidato.
5. Skill Author valida JSON-schema, compila i regex, controlla che
   tutte le primitive citate esistano.
6. Inserisce in `skills` con `status=pending`.
7. Admin vede in `/admin/skills`, modifica se necessario, approva.

**DEFERRED**: `skill_author_enabled=false` di default. Richiede
`cloud_llm_enabled=true` + `ANTHROPIC_API_KEY` in `.env`.

## 9.7 UI admin — `/admin/skills`

**File**: `frontend/src/routes/AdminSkillsPage.tsx`.

Pagina admin con tre tab: **In attesa** / **Attive** / **Disabilitate**.

Per ogni skill: card con name + version + status badge + step count +
intent examples count + lista primitive usate.

Azioni:
- **Modifica** → modal con editor JSON inline + catalogo primitive
- **Approva** → da pending a active
- **Disabilita** → da active a disabled
- **Cancella** → confermato (irreversibile)

L'editor JSON valida client-side prima di POST `/admin/skills/{id}`
(PATCH). Il backend rivalida e rifiuta piani con primitive sconosciute.

## 9.8 Tutorial — creare una skill manualmente

Esempio: skill "riassumi questo articolo" che prende un URL e ritorna
un riassunto in 3 frasi.

**1. Compila il JSON**:

```json
{
  "name": "riassumi_articolo",
  "description": "Da URL articolo → riassunto in 3 frasi",
  "intent_examples": [
    "riassumi questo articolo: https://...",
    "fammi un sommario di questo link",
    "cosa dice questo articolo in breve"
  ],
  "slot_extraction": {
    "url": {
      "method": "regex",
      "pattern": "https?://\\S+",
      "group": 0,
      "required": true
    }
  },
  "plan": {
    "steps": [
      {"id": "fetch", "tool": "read_url",
       "args": {"url": "{url}", "max_chars": 6000}},
      {"id": "tldr", "tool": "summarize",
       "args": {"text": "{fetch.text}", "max_sentences": 3}}
    ]
  },
  "response_template": "Riassunto di **{fetch.title}** ({fetch.source_domain}):\n\n{tldr.summary}",
  "fallback_response": "Non sono riuscita a leggere l'articolo: {error}",
  "status": "pending",
  "auto_authored": false
}
```

**2. Inserisci nel DB** (via API, autenticato come admin):

```bash
TOK=$(curl -sk ... login → access_token)
curl -sk -X POST -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/json" \
  -d @riassumi_articolo.json \
  https://192.168.1.23:8455/api/v1/admin/skills
```

**3. Approvala**:

```bash
SKILL_ID=$(curl ...)  # dal response
curl -sk -X POST -H "Authorization: Bearer $TOK" \
  https://192.168.1.23:8455/api/v1/admin/skills/$SKILL_ID/approve
```

**4. Testa**:

```
Apri chat → "riassumi questo articolo: https://www.repubblica.it/..."
```

Se la skill è ben fatta, vedi il sommario apparire in 5-8 secondi (3-4
sec per fetch + 2-3 sec per summarize).

## 9.9 Telemetria + tuning

Ogni skill hit scrive un `router.skill_hit` event con:

```python
{
  "skill": "ricetta_to_spesa",
  "slots": {"url": "https://..."},
  "summary_len": 47,
  "label": "skill:ricetta_to_spesa",
  "tier": "tier2",
  "confidence": 0.78
}
```

Query questi event per:

- Vedere quale tier sta dominando (se troppo Tier-3, è LLM-bound)
- Identificare skill sotto-utilizzate (candidate alla rimozione)
- Confronto match per tier (tier-2 confidence basse → migliora intent_examples)

```sql
SELECT payload->>'skill', payload->>'tier', count(*)
FROM events
WHERE kind='router.skill_hit' AND ts > now() - interval '7 days'
GROUP BY 1, 2
ORDER BY 3 DESC;
```

---

[← Cap 8 Memoria](08-memoria.md) · [README](README.md) · [Cap 10 Wallet & widgets →](10-wallet-widgets.md)
