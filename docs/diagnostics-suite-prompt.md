# CARA — Spec: suite diagnostica voice-first

## Bug 8: difficile capire se CARA funziona bene · Bug 9: log inaccessibili senza F12 · Bug 10: nessun self-test on-demand

> **Status**: blocca la diagnosi degli altri bug. Quando l'utente
> percepisce "qualcosa non va" non c'è un modo strutturato per dire
> *cosa* non va.

---

## <<<INIZIO PROMPT — DIAGNOSTICS SUITE>>>

<extension_request>

# Sintomi

L'utente segnala ripetutamente "non funziona bene", senza un canale
strutturato per condividere cosa NON funziona. Le sessioni di diagnosi
attuali si fanno via:
- F12 → console del browser (per gli `[cara-stt]` / `[cara-voice]`)
- `docker logs cara-backend` (per gli structlog del backend)
- Test manuali ad-hoc da terminale

Niente di tutto questo è alla portata dell'utente in produzione. Serve:

1. **Una pagina admin "Diagnosi"** che testi ogni componente e dia un
   verdetto (verde/giallo/rosso) + latenze recenti.
2. **Un buffer eventi voce** (ultimi 100 eventi) consultabile dall'admin
   senza F12.
3. **Un overlay di debug nel frontend** attivabile con scorciatoia
   tastiera che mostra in tempo reale TUTTI gli eventi `[cara-*]` in
   sovraimpressione.
4. **Un file di log persistente** strutturato JSON, rotato per data,
   tail-bile dal pannello admin.
5. **Un "self-test" on-demand** che prova in sequenza: STT (tu parli, lei
   trascrive), TTS, intent router, agent loop, riconoscimento facciale,
   accesso alla rete, persistenza DB.

# Componenti da costruire

## A — Endpoint diagnostico backend

`GET /api/v1/admin/diagnostics` (admin-required) ritorna un JSON:

```json
{
  "checks": [
    { "name": "db", "status": "ok", "latency_ms": 12, "detail": "..." },
    { "name": "redis", "status": "ok", "latency_ms": 3, "detail": "..." },
    { "name": "llm", "status": "ok", "latency_ms": null,
      "detail": "model loaded (qwen2.5-1.5b), mode=fast" },
    { "name": "piper_tts", "status": "ok", "detail": "voice paola loaded" },
    { "name": "whisper_asr", "status": "warn",
      "detail": "model not yet loaded (lazy)" },
    { "name": "cda_search", "status": "ok",
      "detail": "DDG reachable, last hit 12 min ago" },
    { "name": "frigate_faces", "status": "ok",
      "detail": "6 people seen in the last hour" },
    { "name": "intent_router", "status": "ok",
      "detail": "10 rules loaded, 8 matches in last 100 queries" }
  ],
  "ts": "2026-05-03T22:15:00Z"
}
```

Status: `ok | warn | error`. Ogni check ha un timeout di 5s; se sfora →
status="error" con detail che spiega perché.

## B — Voice event ring buffer

Un buffer in-memory nel backend che memorizza gli ultimi 200 eventi
strutturati di tipo voice. Eventi catturati:
- intent_router match / no-match (con query e kind)
- chat noise bypass (con query)
- chat agent loop fired
- chat KB cached_answer hit
- LLM swap fast↔quality
- Whisper transcription (con duration, transcribed text length)
- TTS speak request (caller, duration)

Schema evento:
```json
{
  "ts": "2026-05-03T22:15:00.123Z",
  "kind": "intent_router.match" | "chat.noise_bypass" | "chat.agent_loop"
        | "chat.kb_cached" | "llm.swap" | "asr.whisper"
        | "tts.speak" | "chat.routed_intent" | "chat.llm_generate",
  "user_id": 1,
  "duration_ms": 70,
  "data": {...}     /* free-form payload */
}
```

Endpoint: `GET /api/v1/admin/diagnostics/events?limit=100&kind=...`

Implementazione: `collections.deque(maxlen=200)` thread-safe globale.
Ogni service che emette un structlog rilevante chiama anche
`event_log.record(kind, ...)`.

## C — Pagina admin "Diagnosi"

Nuova route `/admin/diagnostics` (admin-only):
- Header: "Diagnosi sistema" + bottone "Aggiorna" + auto-refresh 10s
- Sezione "Stato componenti": griglia con i check di Endpoint A, ognuno
  con pallino colorato (verde/giallo/rosso), nome, latenza, dettaglio
- Sezione "Eventi recenti": tabella degli ultimi 50 eventi dal buffer
  ring (filter chip per kind), espandibile per vedere il payload
- Sezione "Self-test interattivi":
  - Bottone "🔊 Test voce" → lancia un `speak("CARA test, mi senti?")`
    e mostra latenza + se ha completato
  - Bottone "🎤 Test microfono" → apre il mic per 5 sec, mostra il
    transcript
  - Bottone "🌐 Test ricerca" → CDA discover su una query nota
    ("meteo Roma"), mostra fonte trovata + latenza
  - Bottone "🤖 Test LLM" → chiede al LLM "Rispondi solo OK", mostra
    TTFT + tok/s
  - Bottone "👤 Test riconoscimento" → people_present(15min), elenca
    chi vede

Ogni self-test scrive un evento nel ring buffer.

## D — Overlay di debug nel frontend

Nuovo componente `<DebugOverlay>` montato in `App.tsx` ma normalmente
nascosto. Si attiva con `Ctrl+Shift+D` (o long-press di 3s sul logo
nell'angolo della home).

Quando attivo:
- Pannello fisso laterale destro 320px
- Ultimi 100 eventi `[cara-*]` catturati intercettando `console.log`
  (ma solo per i prefissi nostri)
- Filter rapido per prefisso (`stt`, `voice`, `cara-voice`, `tts`, etc)
- Bottone "Cancella" per pulire
- Bottone "Esporta" per scaricare un .json con gli eventi

Persistenza: gli eventi sopravvivono al cambio di route (provider in
`App.tsx`).

## E — File di log persistente

Backend: configurare structlog per scrivere SIA su stdout (come adesso)
SIA su `/app/logs/cara-YYYY-MM-DD.jsonl`. Rotazione giornaliera.
Volume bind in compose: `./data/logs:/app/logs`.

Endpoint admin per il tail: `GET /api/v1/admin/diagnostics/log?lines=200`
ritorna le ultime N righe del log corrente.

## F — Test programmatici (pytest)

Nuova cartella `backend/tests/` con:

- `test_intent_router.py` — il corpus 20+ già scritto, ufficializzato
- `test_noise_bypass.py` — vari livelli di rumore, casi positivi/negativi
- `test_focus_line.py` — verifica che il focus message si infili dove
  deve nel prompt LLM
- `test_cda_kb_cache.py` — flusso "prima volta search, seconda volta KB"
- `test_runtime_context.py` — verifica che la data/ora finisca nel prompt

Comando: `cd backend && .venv/bin/pytest -v`. Niente DB live richiesto:
mockando `setting_svc` e `cda_discover`.

# Vincoli

- Niente nuove dipendenze npm/pip (usa structlog esistente, deque
  Python stdlib, React state).
- L'overlay DebugOverlay deve essere ZERO COSTO quando inattivo (no
  intercettazione di console.log finché non viene aperto).
- Il ring buffer in-memory non deve crescere indefinitamente — `maxlen`
  hard-coded.
- I check del diagnostico devono avere timeout (5s) altrimenti la
  pagina si blocca se un servizio è lento.

# File da creare/toccare

- *(nuovo)* `backend/cara/services/event_log.py` — ring buffer +
  `record(kind, ...)`
- *(nuovo)* `backend/cara/api/v1/diagnostics.py` — endpoint `/admin/diagnostics/*`
- *(nuovo)* `backend/cara/services/diagnostics.py` — esegue i check
- `backend/cara/main.py` — wire structlog file handler
- `backend/cara/services/intent_router.py` — chiama event_log
- `backend/cara/api/v1/chat.py` — chiama event_log su ogni branch
- `backend/cara/services/asr.py` — chiama event_log
- *(nuovo)* `frontend/src/api/diagnostics.ts` — client REST
- *(nuovo)* `frontend/src/routes/DiagnosticsPage.tsx` — UI admin
- *(nuovo)* `frontend/src/components/DebugOverlay.tsx` — overlay
- `frontend/src/App.tsx` — monta DebugOverlay + route /admin/diagnostics
- *(nuovo)* `backend/tests/conftest.py` + `backend/tests/test_*.py`

# Test di accettazione

1. Apri `/admin/diagnostics` come admin. Tutti gli 8 check rispondono
   entro 5s con pallino verde/giallo. Latenza visibile.
2. Premi "Test voce" → CARA pronuncia "CARA test, mi senti?" entro 2s.
3. Premi "Test microfono" → si apre il mic per 5s; il transcript
   compare.
4. Premi "Test LLM" → arriva la risposta; latenza visibile.
5. Premi "Test ricerca" → ottiene un dominio + URL.
6. Apri la chat e parli. Vai su /admin/diagnostics → la sezione
   "Eventi recenti" mostra l'evento intent_router (o noise_bypass) con
   timestamp e payload.
7. Premi `Ctrl+Shift+D` su qualsiasi pagina. Overlay laterale si apre.
   Parli col mic. Gli eventi `[cara-stt]` vi compaiono in tempo reale.
8. Endpoint log tail: `GET /api/v1/admin/diagnostics/log` ritorna le
   ultime 200 righe del file di log corrente.
9. `pytest -v` da `backend/`: passa tutti i test scritti.

</extension_request>

## <<<FINE PROMPT — DIAGNOSTICS SUITE>>>

---

## Note di esecuzione

Effort stimato 3-4 ore: ~1h backend (event_log + diagnostics endpoint
+ checks), ~1h frontend (DiagnosticsPage + DebugOverlay), ~30min file
log + pytest, 30min smoke + commit.
