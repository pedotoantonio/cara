# Cap 32 — Changelog del manuale + roadmap

> *Sintesi 30 secondi.* Storia del manuale del programmatore + cosa
> resta da fare per CARA stessa.

## 32.1 Changelog del manuale

### manual-v0.2.0 — 2026-05-07

**Aggiunti**: capp 4-32 (29 capitoli nuovi, ~13k righe italiani).

Sezioni:
- **Codice (capp 4-5)**: backend e frontend modulo per modulo
- **Funzionalità (capp 6-17)**: AI, voce, memoria, skill, wallet,
  proattività, smart home, CDA, workflow, multi-device, Google,
  notifiche
- **Strumenti (capp 18-21)**: setup wizard, sicurezza, admin,
  diagnostica
- **Ciclo di vita (capp 22-25)**: test, deploy, manutenzione,
  estendere
- **Riferimenti (capp 26-31)**: env vars, admin_settings, API REST,
  WebSocket, glossario, troubleshooting

Documenta lo stato di CARA fino a v1.1.0.

### manual-v0.1.0 — 2026-05-06

Prima release. Capp 0-3:
- Prefazione
- Architettura
- Setup ambiente
- Struttura repository

## 32.2 Cosa manca al manuale

### Screenshot

I capp 5.3 (design system), 9.7 (admin skills), 10.4 (Wallet preset),
15.3 (PairPage), 18.2 (8 step wizard), 19.3 (cert install), 20.1
(admin dashboard) richiederebbero **screenshot reali**.

Effort: ~2h di cattura + ottimizzazione (vedi
`docs/programmer-manual-prompt.md` § 4 per le convenzioni).

### Capitoli da espandere

- **Cap 4-5** — backend/frontend deep-dive: oggi sono "mappa modulare",
  servirebbero esempi più dettagliati per ogni modulo critico
  (cara.ai.llm, cara.api.v1.chat, cara.skills.executor)
- **Cap 9** — Skill Factory: aggiungere case study real (es. "creiamo
  insieme una skill 'meteo della settimana'")
- **Cap 25** — Estendere: un tutorial "creare un workflow nuovo da
  zero" ancora manca

### Tooling automatici

- Script `refresh_linerefs.py` per aggiornare i `file:line`
  automaticamente (vedi prompt § 11.3)
- Script screenshot automatizzato (vedi prompt § 11.4)
- Pandoc PDF generation script

## 32.3 Roadmap CARA stessa

Stato al 2026-05-07: **CARA v1.1.0 in produzione**.

### v1.2.0 — Cloud LLM opt-in (Mese 2 dal v1.0)

Riapri il toggle `cloud_llm_enabled`:

- Skill Author Phase D effettivo (admin clicca "auto-genera skill")
- Email NLU layer 3 attivato (precisione +30% sui casi ambigui)
- Validation pipeline (LLM 3B locale + Haiku second opinion)

**Costo**: ~$2-5/mese per famiglia tipica (1000 chat/mese × $0.005).

### v1.3.0 — Skill Factory Phase F + G

- Phase F: migrare gli intent hardcoded restanti (`add_task`,
  `add_shopping`, `list_tasks`, ecc.) come skill JSON. Eliminerebbe
  `intent_router.py` e `recipe_chain.py` legacy.
- Phase G: skill conditional (`if condition then step1 else step2`)
  oltre al lineare attuale. Permetterebbe skill più complesse.

### v1.4.0 — Multi-family (multi-tenant)

Aggiungere il concetto di `Family` come entità top-level:

- `family_id` su tutte le tabelle
- Family bus per family
- Provider OAuth multi-account per family
- Setup wizard supporta "famiglia + admin", non solo "admin"

Sblocca uso non-domestico (uffici piccoli, classi scuola).

### v1.5.0 — Hardware Wall Pi 5

- Procedura di build fisica (Pi 5 + 7" touchscreen + custodia)
- Kiosk mode auto-launch
- Surface UI customizations (font grandi, gesture-based)
- Voce sempre-on con wake word affidabile (PyAudio + porcupine
  esplorato)

BoM ~€450. Apre il "vero" caso d'uso domestic AI assistant
multi-room.

### v1.6.0 — Plugin marketplace (esplorativo)

Permettere a sviluppatori esterni di pubblicare:

- Skill JSON
- Widget custom
- Workflow custom
- Rules proattività

In un repository git pubblico (cara-plugins), CARA scarica + valida
+ installa con conferma admin. Sandboxing python via subinterpreters
o Docker.

### v2.0.0 — Riscrittura completa? Forse.

Solo se la community CARA cresce e vogliamo:
- Backend Rust (pyo3 wrapper attuale → puro Rust)
- Frontend SolidJS (React → fini-grained reactive, meno overhead)
- Plugin sandboxing reale
- Internationalization (EN, FR, ES)

Difficilmente prima del 2027.

## 32.4 Roadmap interna a CARA

Cose specifiche che il maintainer aggiunge nel tempo:

- [ ] Refresh `file:line` script automatico nel manuale
- [ ] CI GitHub Actions per smoke + unit auto su PR
- [ ] Endpoint `/admin/maintenance/restart` per restart auto post-setup
- [ ] Token blocklist per revoke immediate device (cap 19.12)
- [ ] Multi-family preparation (refactor `family_id` foreign key)
- [ ] WebRTC audio invece di SSE+WebAudio (latenza dimezzata)
- [ ] Image search per CDA (visual content discovery)
- [ ] Voice fingerprinting per identificazione speaker

## 32.5 Contributi

Se trovi un bug nel manuale o vuoi aggiungere una sezione, edita il
file relativo, fai PR.

Convenzioni:
- Italian semplice (cap 0 ha le linee guida)
- Frasi ≤25 parole
- Voce attiva
- Callout standard (💡⚠️🔒)

Apri un issue prima per decidere insieme se il cambio ha senso.

## 32.6 Ringraziamenti

Questo manuale è stato scritto da **Claude Sonnet 4.6** (Anthropic) su
prompt di Antonio Pedoto, seguendo la spec
`docs/programmer-manual-prompt.md`. Tempo totale di scrittura: ~3
giorni di sessioni cumulative, distribuiti su Maggio 2026.

Le scelte di design di CARA stessa sono di Antonio. Le implementazioni
sono frutto di lavoro di coppia umano + AI nel periodo Aprile-Maggio
2026.

Buon viaggio.

---

[← Cap 31 Troubleshooting](31-troubleshooting.md) · [README](README.md)
