# CARA — Manuale del Programmatore

> Versione manuale: **0.2.0** · Versione CARA documentata: **1.1.0** · Aggiornato: 2026-05-07

Questa è la documentazione tecnica completa di CARA — l'assistente AI di
casa che gira sul NanoPC-T6. Se sei arrivato qui sei un programmatore
intermedio (Python + React) che vuole capire come funziona CARA dentro,
modificarla, estenderla, o gestirla in produzione.

Il manuale è scritto in italiano semplice ma tecnicamente preciso. Ogni
capitolo è autoportante: puoi leggerlo da solo se hai i prerequisiti
indicati. I rimandi `file:line` puntano alla codebase di CARA.

Se vuoi solo **avviare** CARA senza guardarla dentro, leggi
`/opt/cara/docs/MANUALE-FAMIGLIA.md` (per la famiglia) o
`MANUALE-ADMIN.md` (per chi la configura). Questo manuale è per chi
vuole **toccare il codice**.

---

## Come è organizzato il manuale

Il manuale ha 32 capitoli divisi in 7 grandi aree:

| Area | Capitoli | A cosa serve |
|---|---|---|
| **Fondamenti** | 0-3 | Cosa è CARA, come è strutturata, come la avvi sul tuo PC |
| **Codice** | 4-5 | Backend Python e frontend React, modulo per modulo |
| **Funzionalità** | 6-17 | Ogni feature spiegata: AI, voce, memoria, skill, ecc. |
| **Strumenti** | 18-21 | Setup wizard, sicurezza, admin panel, debug |
| **Ciclo di vita** | 22-25 | Test, deploy, manutenzione, come estendere CARA |
| **Riferimenti** | 26-31 | Tabelle: variabili, settings, API, glossario, troubleshooting |
| **Storia** | 32 | Changelog del manuale + roadmap futura |

---

## Indice completo

### Fondamenti

- [Cap 0 — Prefazione](00-prefazione.md) · *Filosofia del progetto, target utenti, stato attuale*
- [Cap 1 — Architettura](01-architettura.md) · *Vista d'insieme, stack, container, rete, storage, data flow*
- [Cap 2 — Setup ambiente di sviluppo](02-setup-ambiente.md) · *Da zero a CARA che gira sul tuo PC*
- [Cap 3 — Struttura del repository](03-struttura-repo.md) · *Albero directory, convenzioni, branch e commit*

### Backend e frontend

- [Cap 4 — Backend, moduli profondi](04-backend-moduli.md) · *I 16 sotto-pacchetti `cara.*` mappati uno per uno*
- [Cap 5 — Frontend, moduli profondi](05-frontend-moduli.md) · *Stack React/Vite/Tailwind/PWA, design system, API client*

### Funzionalità

- [Cap 6 — AI / LLM](06-ai-llm.md) · *Qwen 2.5-1.5B, RKLLM, KV cache TTFT 8.3×, sampling, system prompt*
- [Cap 7 — Voce, TTS, STT](07-voce-tts-stt.md) · *Piper TTS, sentence streaming, Whisper, Web Speech, wake word*
- [Cap 8 — Memoria](08-memoria.md) · *Episodic + semantic, fact extraction, top-k retrieval, GDPR*
- [Cap 9 — Skill Factory](09-skill-factory.md) · *JSON skill, primitive, executor, dispatcher Tier-1/2/3, Skill Author*
- [Cap 10 — Wallet & widgets](10-wallet-widgets.md) · *Engine, 13 widget, layout per surface, 4 preset profili*
- [Cap 11 — Proattività](11-proattivita.md) · *Engine + 10 rules concrete, scheduler, silent hours*
- [Cap 12 — Smart home](12-smart-home.md) · *HA REST + WS adapter, NLU 4-stadi, permessi per ruolo, alias*
- [Cap 13 — CDA (Content Discovery)](13-cda.md) · *Search → discovery → verify → KB, rate limit, safe search minori*
- [Cap 14 — Workflow](14-workflow.md) · *Receipt, Bill, Recipe + auto-confirm trust streak*
- [Cap 15 — Multi-device + pairing](15-multi-device.md) · *Pairing 6-cifre, surface (mobile/wall/watch), JWT 1 anno*
- [Cap 16 — Integrazioni Google](16-integrazioni-google.md) · *Calendar 2-way sync, Gmail readonly garantito, NLU 3-livelli*
- [Cap 17 — Notifiche e bus famiglia](17-notifiche-bus.md) · *VAPID push, family bus Redis pub/sub + WebSocket*

### Strumenti

- [Cap 18 — Setup wizard `/setup`](18-setup-wizard.md) · *8 step, italian-first, idempotente, resumable*
- [Cap 19 — Sicurezza](19-sicurezza.md) · *JWT, bcrypt, AES-GCM OAuth tokens, mkcert TLS, audit log*
- [Cap 20 — Pannello admin](20-pannello-admin.md) · *Settings, audit, sub-pages admin, KV cache flush*
- [Cap 21 — Diagnostica e debug](21-diagnostica-debug.md) · *Diagnostics suite, sysadmin dashboard, debug overlay, structlog*

### Ciclo di vita

- [Cap 22 — Test](22-test.md) · *Unit (in-memory SQLite), smoke (httpx vs live), Playwright E2E*
- [Cap 23 — Deploy](23-deploy.md) · *docker compose --profile app, migration, restart, rollback*
- [Cap 24 — Manutenzione](24-manutenzione.md) · *Backup Postgres, KV cache cleanup, aggiornamento modello/voci*
- [Cap 25 — Estendere CARA (tutorial pratici)](25-estendere-cara.md) · *Endpoint, widget, rule, primitive, migration, webhook*

### Riferimenti

- [Cap 26 — Riferimento variabili `.env`](26-env-vars.md) · *Tabella di tutte le env vars per dominio*
- [Cap 27 — Riferimento `admin_settings`](27-admin-settings.md) · *Tutti i flag runtime modificabili*
- [Cap 28 — Riferimento API REST](28-api-rest.md) · *~149 endpoint elencati per dominio*
- [Cap 29 — Riferimento WebSocket](29-websocket.md) · *Family bus topic + payload format*
- [Cap 30 — Glossario](30-glossario.md) · *Definizioni dei termini tecnici CARA*
- [Cap 31 — Troubleshooting](31-troubleshooting.md) · *16 scenari di problema + diagnosi + fix*

### Storia

- [Cap 32 — Changelog del manuale + roadmap](32-changelog-roadmap.md) · *Cronologia release manuale + futuro CARA*

---

## Come leggere questo manuale

Tre percorsi consigliati a seconda di chi sei:

### Sei nuovo a CARA, vuoi una visione completa
Leggi nell'ordine: cap 0 → 1 → 2 → 3. Dopo, salta direttamente alle
funzionalità che ti interessano (cap 6-17). I capitoli 4 e 5 sono
densi: leggili solo quando devi modificare il codice di un modulo
specifico.

### Devi modificare una feature precisa
Salta direttamente al capitolo che la copre. Ogni capitolo include
la sezione "Come estenderlo" con un mini-tutorial. Se ti serve più
profondità, il cap 25 raccoglie i tutorial completi.

### Devi solo deployare o manutenere
Leggi cap 1 (per la mappa) → cap 22 (test) → cap 23 (deploy) →
cap 24 (manutenzione) → cap 31 (troubleshooting).

---

## Convenzioni usate

- **`backtick`** sui percorsi file, comandi, nomi di funzione: `cara/api/v1/setup.py`, `flush_all()`, `docker compose up -d`
- **`file:linea`** per riferimenti precisi al codice: `cara/api/v1/setup.py:120`. I numeri di riga si riferiscono alla versione di CARA indicata in cima a ogni capitolo.
- **Blocchi codice** sempre con linguaggio:
  ```python
  from cara.skills.registry import primitive
  ```
- **Tre tipi di callout**:

> **💡 Suggerimento** — usa `make logs-backend` invece di
> `docker logs cara-backend` per evitare di battere ogni volta.

> **⚠️ Attenzione** — la migration `c8a7d94e1f02` non è reversibile:
> testa il rollback su un ambiente staging prima.

> **🔒 Sicurezza** — non loggare mai il `password_hash` in chiaro.
> Usa `mask_secret()` da `cara/services/env_writer.py`.

---

## Contributi al manuale

Il manuale vive in `docs/manual/`. Quando modifichi codice in `cara/*`
o `frontend/src/*` in modo non-banale, aggiorna il capitolo
corrispondente nello stesso PR. Lo script `docs/manual/scripts/refresh_linerefs.py`
aggiorna i riferimenti `file:linea` se il codice si è spostato — eseguilo
prima di committare.

Per generare il PDF completo:

```bash
cd docs/manual
pandoc README.md 0?-*.md 1?-*.md 2?-*.md 3?-*.md \
  -o cara-manuale.pdf \
  --pdf-engine=xelatex --toc --toc-depth=3 \
  -V mainfont="Source Serif Pro" -V monofont="JetBrains Mono" \
  -V geometry:margin=2cm -V lang=it
```

---

> **Status**: tutti i 32 capitoli sono completi nella versione 0.2.0.
> Mancano gli **screenshot** (effort separato di ~2h cattura+ottimizzazione,
> vedi [docs/programmer-manual-prompt.md](../programmer-manual-prompt.md)
> § 4 per le convenzioni). Il changelog dettagliato del manuale è in
> [Cap 32](32-changelog-roadmap.md).
