# CARA v1.0 — Handoff document, branch `epic-0-foundations`

Stato a fine sessione 2026-05-04 (consolidata in due ondate). **195 test verdi** (180 unit + 15 smoke).

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

Migrazioni Alembic applicate al DB live (`cara-postgres`):
`c8a7d94e1f02 → d4e1f8b3a201 → e8a2c5f7b310`. Idempotenti, downgrade
testabile.

## Cosa NON è stato fatto (di proposito)

Tutti gli step che richiedono di toccare file nel working tree del tuo
Step 66 sono rimasti **fuori scope** finché non commiti. Concretamente:

| Step bloccato | Motivo |
|---------------|--------|
| 0.2 — spezzare `chat.py` 1151 righe | `chat.py` modified nel tuo working tree |
| 0.5 — abilitare `prompt_cache_params` RKLLM | `cara/ai/llm.py` non l'ho voluto rischiare in parallelo |
| 1.3 — TTS streaming chunked | tocca `chat.py` + `tts/service.py` |
| 1.5 — system prompt corto + segmentato | tocca `chat.py` |

Tutte le infrastrutture (episodic, tool_metrics, router, normalizer,
cache, weather) sono pronte per essere **wirate** quando questi Step
diventano sbloccati.

## Cosa devi fare per riprendere

### 1. Committa il tuo Step 66

Tutti i file modified + untracked nel working tree che hai descritto
come Skill Factory v0.7. Suggerimento di commit (puoi usare il tuo
nome utente):

```bash
cd /opt/cara
git checkout main  # o resta su epic-0-foundations e fai un branch a parte
git add backend/cara/api backend/cara/cda backend/cara/config.py \
        backend/cara/main.py backend/cara/models backend/cara/services \
        backend/cara/skills backend/cara/core backend/cara/store \
        backend/alembic/versions/6061bac37e44_add_skills_table.py \
        backend/alembic/versions/c8a7d94e1f02_seed_skill_ricetta_to_spesa.py \
        frontend/src docs/skill-factory-extension-prompt.md
git commit -m "feat: Step 66 — Skill Factory v0.7 vertical slice + recipe_chain + verify_streams"
```

(Adatta il messaggio. L'importante è che lo Step 66 finisca in un singolo
commit identificabile.)

### 2. Mergia `epic-0-foundations` su `main`

```bash
git checkout main
git merge epic-0-foundations
make test  # deve dare 107/107 verde
```

Se ci sono conflitti, dovrebbero essere zero o quasi: io non ho toccato
nessuno dei file che hai editato tu. Le uniche cose che potrebbero
collidere sono `pyproject.toml` (ho aggiunto `pyyaml`) e
`alembic_version` nel DB (già `e8a2c5f7b310`, due step avanti).

### 3. Aggiungi i nuovi modelli a `cara/models/__init__.py`

Quando il merge è pulito, aggiungi nel tuo `__init__.py` (che adesso
contiene anche `Skill`):

```python
from cara.models.device import Device
from cara.models.event import Event
from cara.models.fact import Fact
from cara.models.tool_metric import ToolCallMetric

__all__ = [
    # ... le tue voci esistenti ...
    "Device",
    "Event",
    "Fact",
    "ToolCallMetric",
]
```

Quattro classi nuove. Le ho lasciate fuori per evitare conflitti col tuo working tree.

### 4. Step 0.2 — refactor `chat.py`

Adesso che il working tree è pulito, posso (o puoi) iniziare a spezzare
`chat()` in stage del nuovo Pipeline. Ordine consigliato:

1. Estrai `_render_qwen_prompt`, `_runtime_context_message` in un nuovo
   `prompt_builder.py`.
2. Estrai parser tool call e dispatch in `tool_dispatch.py` — wira al
   volo il `tool_metrics.record_attempt` per ogni tentativo.
3. Estrai grounding (`_needs_grounding`, `_infer_kind`,
   `_has_discover_tool`) in `grounding.py`.
4. Trasforma il routing inline (`intent_router → recipe_chain → skills →
   tool_calling → fallback`) in 5 `Stage` del `Pipeline`. Cache stage si
   inserisce per primo.
5. `episodic.record` su ogni decisione: `router.stage`, `tool.call`,
   `chat.turn`.
6. Smoke test deve passare invariato. Se non passa, il refactor sta
   cambiando il comportamento esterno → fermarsi e investigare.

Target: `chat()` <250 righe.

### 5. Step 0.5 — KV cache RKLLM

Una linea in `cara/ai/llm.py:230` (dove `infer.prompt_cache_params =
None`). Crea un `RKLLMPromptCacheParam` con un percorso per-conversation
sotto `/app/cache/kv/<conversation_id>.bin`. Invalidation: cambio system
prompt → flush all; conversazione idle 30 min → file remove.

### 6. Step 1.3 e 1.5

Step 1.3 (TTS streaming chunked) e Step 1.5 (system prompt segmentato +
corto): entrambi nel post-refactor di `chat.py`, dove ognuno è una
modifica chirurgica di poche righe.

## Stato Alembic

```
$ alembic current
d6e2f9a4d825 (head)
```

Catena completa:
```
e7ff (initial) → df31 (users) → b984 (tasks) → 8ac2 (task_due) → ed5d (shopping)
  → 04f5 (notes) → c64d (user_role) → 1727 (admin_settings+audit)
  → 0efc (user_birth_date) → d1b1 (files) → a3f1 (cda)
  → 6061 (skills) ← Antonio Step 66
  → c8a7 (seed ricetta) ← Antonio Step 66
  → d4e1 (events) ← Step 0.3
  → e8a2 (tool_call_metrics) ← Step 0.4
  → f3c9 (devices) ← Step 6.3
  → d6e2 (facts) ← Step 2.2
```

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

**14 Step** completati come **infrastruttura pronta per il wiring**:

- **Epic 0** (foundations): 0.1 + 0.3 + 0.4 + 0.6 — bloccati 0.2 + 0.5
- **Epic 1** (voce): 1.1 + 1.4 — bloccati 1.2 + 1.3 + 1.5
- **Epic 2** (memoria): 2.1 + 2.2 + 2.3
- **Epic 3** (workflow): 3.1 + 3.2
- **Epic 5** (smart home): 5.1
- **Epic 6** (multi-device): 6.3
- **Epic 8** (proattività): 8.1

Nessun comportamento utente è cambiato (tutto additivo). **195 test
verdi** proteggono il prossimo refactor di `chat.py`. Quando commiti
il tuo Step 66, in una giornata si chiudono i 4 step bloccati (0.2 +
0.5 + 1.3 + 1.5) e l'infrastruttura sopra inizia a essere wired uno
per uno: episodic.record nelle hot path, semantic facts iniettati nel
system prompt, response cache come primo stage del Pipeline, weather
expose come endpoint REST, NER+OCR consumate dal ReceiptWorkflow, etc.

**Pacchetti nuovi** disponibili nel codebase: `cara.learning`,
`cara.router`, `cara.workflows`, `cara.smarthome`, oltre alle
estensioni di `cara.ai` (embeddings/ner/ocr/tts.normalizer) e
`cara.services` (response_cache/weather).
