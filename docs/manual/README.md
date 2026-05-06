# CARA — Manuale del Programmatore

> Versione manuale: **0.1.0** · Versione CARA documentata: **1.1.0** · Aggiornato: 2026-05-06

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

- Cap 4 — Backend, moduli profondi *(in scrittura)*
  - 4.1 cara.config · 4.2 cara.store · 4.3 cara.models · 4.4 cara.api.v1
  - 4.5 cara.api.deps · 4.6 cara.services · 4.7 cara.ai · 4.8 cara.cda
  - 4.9 cara.core · 4.10 cara.integrations · 4.11 cara.learning
  - 4.12 cara.router · 4.13 cara.skills · 4.14 cara.smarthome
  - 4.15 cara.widgets · 4.16 cara.workflows
- Cap 5 — Frontend, moduli profondi *(in scrittura)*

### Funzionalità

- Cap 6 — AI / LLM (Qwen, RKLLM, KV cache, sampling, system prompt) *(in scrittura)*
- Cap 7 — Voce, TTS, STT *(in scrittura)*
- Cap 8 — Memoria (episodic + semantic) *(in scrittura)*
- Cap 9 — Skill Factory *(in scrittura)*
- Cap 10 — Wallet & widgets *(in scrittura)*
- Cap 11 — Proattività *(in scrittura)*
- Cap 12 — Smart home *(in scrittura)*
- Cap 13 — CDA (Content Discovery Agent) *(in scrittura)*
- Cap 14 — Workflow (Receipt, Bill, Recipe) *(in scrittura)*
- Cap 15 — Multi-device + pairing *(in scrittura)*
- Cap 16 — Integrazioni Google *(in scrittura)*
- Cap 17 — Notifiche e bus famiglia *(in scrittura)*

### Strumenti

- Cap 18 — Setup wizard `/setup` *(in scrittura)*
- Cap 19 — Sicurezza *(in scrittura)*
- Cap 20 — Pannello admin *(in scrittura)*
- Cap 21 — Diagnostica e debug *(in scrittura)*

### Ciclo di vita

- Cap 22 — Test (unit, smoke, E2E) *(in scrittura)*
- Cap 23 — Deploy *(in scrittura)*
- Cap 24 — Manutenzione *(in scrittura)*
- Cap 25 — Estendere CARA (tutorial pratici) *(in scrittura)*

### Riferimenti

- Cap 26 — Riferimento variabili `.env` *(in scrittura)*
- Cap 27 — Riferimento `admin_settings` *(in scrittura)*
- Cap 28 — Riferimento API REST *(in scrittura)*
- Cap 29 — Riferimento WebSocket *(in scrittura)*
- Cap 30 — Glossario *(in scrittura)*
- Cap 31 — Troubleshooting *(in scrittura)*
- Cap 32 — Changelog del manuale + roadmap *(in scrittura)*

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

> Il manuale è **un'opera in corso**. I capitoli 0-3 sono completi
> nella versione 0.1.0; gli altri arrivano nelle prossime release. Il
> changelog dettagliato è in [Cap 32](32-changelog-roadmap.md) (quando
> sarà pronto).
