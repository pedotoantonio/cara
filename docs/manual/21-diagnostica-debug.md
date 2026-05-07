# Cap 21 — Diagnostica e debug

> *Sintesi 30 secondi.* Tre strumenti per capire cosa succede dentro
> CARA: la **Diagnostics suite** in `/admin/diagnostics` (health
> sistema), la **Sysadmin Dashboard** (host metrics + container), e il
> **Debug overlay** in-app (Ctrl+Shift+D mostra eventi `[cara-*]` live).
> Più i log strutturati structlog del backend.

## 21.1 Sysadmin dashboard — host esterno

Container separato `sysadmin-dashboard` su porta 3080. Non è parte
di CARA tecnicamente, ma mappa l'intero NanoPC + tutti i container
inclusi quelli CARA.

URL: `http://192.168.1.23:3080/`

Funzioni:
- Monitoring sistema (CPU, RAM, disco, temp)
- Lista container Docker + stato + log tail
- Web terminal (shell host via xterm.js)
- SNMP traps receiver
- Alerting auto: disco >90%, RAM >90%, container crashed

Vedi `/home/apedo/CLAUDE.md` § "Sysadmin Dashboard".

## 21.2 Diagnostics suite — `/admin/diagnostics`

**File**: `frontend/src/routes/DiagnosticsPage.tsx` + backend
`cara/api/v1/diagnostics.py` + `cara/services/diagnostics.py`.

Pagina admin con check di salute interni a CARA.

```
+-------------------------------------+
| Diagnostica CARA                     |
+-------------------------------------+
| ✓ Database               (10ms)     |
| ✓ Redis                   (3ms)      |
| ✓ MinIO                   (8ms)      |
| ⚠ ChromaDB              (timeout)   |
| ✓ LLM caricato                       |
|     model: qwen2.5-1.5b-instruct     |
|     warm: true                       |
| ✓ TTS Piper                          |
| ✓ Home Assistant         (45ms)     |
| ✓ Frigate                (32ms)     |
| ✓ Push scheduler          (running)  |
| ✓ Calendar sync          (running)  |
| ✓ Gmail scanner           (running)  |
+-------------------------------------+
| Eventi recenti (ultime 10)            |
| 14:02:15 chat.turn ok 2.1s            |
| 14:01:48 router.skill_hit             |
| 14:01:23 ha.state_changed light.cucina|
| ...                                    |
+-------------------------------------+
| Self-test on-demand [Esegui]         |
+-------------------------------------+
```

### Endpoints

```
GET  /api/v1/diagnostics/health      → check tutti i sub-system
POST /api/v1/diagnostics/self-test   → smoke test completo
GET  /api/v1/diagnostics/events      → ultimi eventi episodic
GET  /api/v1/diagnostics/scheduler-status → tasks asyncio attivi
```

### Self-test

Esegue 8 test reali end-to-end:

1. DB write+read in tabella `diagnostics_test`
2. Redis SET+GET con TTL 5s
3. MinIO upload+download oggetto small
4. LLM 1-token generation (warmup verify)
5. TTS sintesi "test" (2 char)
6. NER detect su "Antonio è allergico ai pomodori"
7. Embedding encode di "test" (verify model loaded)
8. CDA discover dummy query (verify search chain)

Output: pass/fail per ogni test, con tempo. Se uno fallisce,
diagnostics fa il drill-down (es. DB fallito → mostra l'errore SQL).

## 21.3 Debug overlay (Ctrl+Shift+D)

**File**: `frontend/src/components/DebugOverlay.tsx`.

Premi `Ctrl+Shift+D` (o `Cmd+Shift+D` Mac) in qualsiasi pagina CARA
loggata. Si apre un overlay full-width che mostra eventi `[cara-*]`
emessi dal frontend in tempo reale.

```
+----------------------------------------+
| Debug overlay  [pause] [clear] [×]    |
+----------------------------------------+
| 14:32:01 [cara-chat] sse.token tok=ciao|
| 14:32:01 [cara-chat] sse.token tok=,   |
| 14:32:01 [cara-chat] sse.audio_chunk   |
|          seq=1 len=3247                  |
| 14:32:00 [cara-router] match-tier1      |
|          intent=answer_datetime         |
| 14:31:59 [cara-tts] piper.synth dur=380ms|
| ...                                      |
+----------------------------------------+
```

Ogni evento ha timestamp + namespace + key/value. Generato da
`window.dispatchEvent(new CustomEvent("cara-<ns>", {detail}))`.

Utile per:
- Verificare il flow SSE chat senza F12 dev tools
- Misurare latenze percepite
- Dimostrazione live a chi non sa "cosa fa CARA"

## 21.4 Log structlog — `docker logs`

CARA backend usa `structlog`. Output formato:

```
2026-05-07 12:34:56 [info     ] chat.turn   tokens=42 first_token_seconds=2.1 user_id=1
2026-05-07 12:34:55 [warning  ] proactivity.rule.exception error="..." rule_id=budget_drift_warning
2026-05-07 12:34:54 [info     ] router.miss message="..." user_id=1
```

```bash
# Tail live
docker logs -f cara-backend

# Filtra per evento
docker logs cara-backend | grep "router\."

# Ultimi N
docker logs --tail 100 cara-backend

# Solo warning + sopra
docker logs cara-backend 2>&1 | grep -E "warning|error"
```

### Convenzioni structlog

Eventi nominati **dotted**: `chat.turn`, `router.miss`,
`setup.step.tls`. I namespace: `chat.*`, `router.*`, `skill.*`,
`integration.*`, `setup.*`, `cda.*`, `tts.*`, `llm.*`,
`proactivity.*`, `family_bus.*`.

Mai `print()`. Mai f-string formattate; sempre key=value:

```python
# Buono
log.info("chat.turn", tokens=tokens, ttft=ttft)

# Cattivo
print(f"chat.turn tokens={tokens} ttft={ttft}")
log.info(f"chat.turn tokens={tokens}")
```

Cosi i log sono filtrabili per chiave.

### Log levels

- `DEBUG` — dettagli interni (singoli token, retry interni). Spento in
  prod.
- `INFO` — eventi normali (request completati, scheduler tick)
- `WARNING` — qualcosa ma recoverable (rate limit hit, integrazione
  giù temporaneamente)
- `ERROR` — bug logico o servizio rotto
- `CRITICAL` — backend deve riavviarsi

Configura via `CARA_LOG_LEVEL=DEBUG` in `.env`.

## 21.5 Eventi episodic — query SQL diretto

Il `events` table è la fonte di verità per debug "cosa è successo".

```sql
-- Ultime 50 chat turns
SELECT ts, user_id, payload->>'tokens' AS tokens,
       payload->>'first_token_seconds' AS ttft
FROM events
WHERE kind='chat.turn'
ORDER BY ts DESC
LIMIT 50;

-- Distribuzione miss del router
SELECT date_trunc('hour', ts) AS hour, count(*)
FROM events
WHERE kind='router.miss' AND ts > now() - interval '7 days'
GROUP BY 1
ORDER BY 1;

-- Top intent matchato
SELECT payload->>'intent' AS intent, count(*)
FROM events
WHERE kind='router.intent_hit' AND ts > now() - interval '1 day'
GROUP BY 1
ORDER BY 2 DESC;

-- Latency p95 chat
SELECT
  date_trunc('hour', ts) AS hour,
  percentile_cont(0.5)  WITHIN GROUP (ORDER BY duration_ms) AS p50,
  percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95
FROM events
WHERE kind='chat.turn' AND ts > now() - interval '1 day'
GROUP BY 1
ORDER BY 1;
```

Connessione `psql`:

```bash
docker exec -it cara-postgres psql -U cara -d cara
```

## 21.6 Tool call funnel — diagnostica tool-calling

Quando il modello chiama un tool tipo `[TOOL: add_task ...]`, ogni
tentativo è loggato in `tool_call_metrics` con la stage in cui ha
fallito.

```sql
-- Funnel ultima settimana
SELECT
  count(*) FILTER (WHERE parse_ok) AS parsed,
  count(*) FILTER (WHERE name_match) AS name_ok,
  count(*) FILTER (WHERE args_valid) AS args_ok,
  count(*) FILTER (WHERE executed) AS executed,
  count(*) AS total
FROM tool_call_metrics
WHERE ts > now() - interval '7 days';

-- Top error_class
SELECT error_class, count(*)
FROM tool_call_metrics
WHERE NOT executed AND ts > now() - interval '7 days'
GROUP BY 1
ORDER BY 2 DESC;

-- Esempi recenti di typo_prefix
SELECT raw_call, ts, tool_name
FROM tool_call_metrics
WHERE error_class='typo_prefix'
ORDER BY ts DESC LIMIT 10;
```

Endpoints REST in `/admin/tool-metrics/*` (cap 20.7).

## 21.7 Profilazione — flame graph LLM

Per capire dove va il tempo nei turni LLM lenti:

```bash
docker exec cara-backend python -c "
import asyncio, time
from cara.ai.llm import get_llm_service

async def main():
    svc = get_llm_service()
    t0 = time.perf_counter()
    async for chunk in svc.generate('Ciao', max_new_tokens=50):
        print(time.perf_counter() - t0, chunk.text[:30])
    print('total:', time.perf_counter() - t0)

asyncio.run(main())
"
```

Più sofisticato: `py-spy` su PID del backend per flame graph realistico.
Non istallato di default (richiede privilege ptrace).

## 21.8 NPU diagnostics

Verifica che la NPU funzioni:

```bash
# Driver version
sudo cat /sys/kernel/debug/rknpu/version
# v0.9.8 atteso

# Load attuale
sudo cat /sys/kernel/debug/rknpu/load
# 0% idle, ~100% during inference

# Memory usage
sudo cat /sys/kernel/debug/rknpu/mm
# mostra MB allocati
```

Se la NPU mostra 0% durante una chat, c'è un problema di binding.
Verifica nei log backend:

```
docker logs cara-backend | grep "rkllm-runtime"
# Atteso: rkllm-runtime version: 1.1.0, rknpu driver version: 0.9.8
```

## 21.9 Container metrics

```bash
# Stats real-time
docker stats cara-backend cara-frontend cara-postgres cara-redis

# Health status
docker compose ps

# Network
docker network inspect proxy-net
```

## 21.10 Errori comuni

| Sintomo | Diagnostica | Risoluzione |
|---|---|---|
| Backend lento | `docker stats cara-backend` → CPU 100%? | Frigate sta rubando CPU; cap container |
| LLM TTFT >30s | KV cache non funziona | Verifica `/app/cache/kv/` scrivibile |
| WebSocket frequenti disconnect | nginx-proxy timeout | Aumenta `proxy_read_timeout` |
| Memory leak | `docker stats` mostra growth | Restart periodic OK; investigare se >2GB |
| Logs strutturati persi | Buffer `docker logs` | Limita rotation: `max-size: 10m`, `max-file: 3` in compose |

## 21.11 Tutorial — debugging un router miss

Scenario: utente dice "che giorno è?" ma il router fa miss e va al
LLM (lenta), invece di Tier-1 intent_router.

**1. Verifica nei log**:

```bash
docker logs cara-backend | grep -A1 "che giorno"
```

Output:
```
[info] router.miss message="che giorno è?"
```

**2. Verifica intent_router**:

```python
# In una shell Python dentro il container
docker exec -it cara-backend python -c "
from cara.services.intent_router import detect_intent
r = detect_intent('che giorno è?')
print(r)
"
```

Se ritorna `None` → il pattern manca. Se ritorna intent → ma il router
non lo ha matchato → bug nel chiamante.

**3. Aggiungi pattern**: edita `cara/services/intent_router.py`,
aggiungi un regex per "che giorno è" → kind `answer_datetime`.

**4. Test smoke**:

```bash
docker cp backend/cara/services/intent_router.py cara-backend:/app/...
# senza restart? Sì se non cambia struttura, no per modifiche di import
docker restart cara-backend
sleep 10

# Test live
curl -sk -N -X POST https://192.168.1.23:8455/api/v1/chat \
  -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/json" \
  -d '{"message":"che giorno è?"}'
```

Output atteso: SSE con `routed=intent:answer_datetime` e risposta
canned veloce (no LLM).

**5. Verifica negli eventi**:

```sql
SELECT * FROM events
WHERE kind='router.intent_hit' AND ts > now() - interval '1 min';
```

Una riga con il nuovo pattern → conferma fix.

---

[← Cap 20 Pannello admin](20-pannello-admin.md) · [README](README.md) · [Cap 22 Test →](22-test.md)
