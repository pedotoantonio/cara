# CARA — Manuale del Programmatore (prompt di scrittura)

**Tipo**: prompt di consegna per uno scrittore tecnico (umano o agente
AI) che produrrà il manuale completo del programmatore CARA, in
italiano, con screenshot di riferimento.

**Obiettivo finale**: una documentazione di livello professionale che
permetta a uno sviluppatore esterno (o ad Antonio fra sei mesi, quando
avrà dimenticato i dettagli) di **leggere, capire, modificare,
estendere e gestire CARA in produzione** senza dover risalire la
storia git o aprire un'altra fonte.

Il manuale deve essere **chiaro come un libro per persone curiose**,
non come uno spec engineering arido: italiano semplice, frasi corte,
esempi concreti, ma **profondità tecnica vera** quando il lettore
vuole approfondire.

---

## 1. Pubblico e tono

**Lettore tipo**: sviluppatore di livello intermedio che conosce
Python e React ma **non** conosce CARA. Sa cosa è un container, un
JWT, un database, ma non sa cosa è RKLLM, cosa fa la pipeline router
di CARA, o perché è stata scelta `injectManifest` mode.

**Tono**:

- **Italiano semplice** — niente "implementazione", scrivi "come è
  fatto"; niente "leveraging", scrivi "uso". Vocabolario quotidiano,
  termini tecnici inglesi solo quando sono lo standard di settore
  (database, container, endpoint, deploy, OAuth).
- **Frasi corte**. Una idea per frase. Massimo 25 parole.
- **Voce attiva**. "Il backend scrive in `events`", non "viene scritto
  un evento dal backend".
- **"Tu" diretto**. "Aggiungi un campo al modello, poi crei una
  migration." Non "il programmatore dovrebbe...".
- **Metafore concrete** dove aiutano. Esempi presi dalla vita: la KV
  cache è "come tenere la pasta sul fuoco invece di rimettere a bollire
  l'acqua ogni volta".
- **Niente buzzword**. Mai "synergy", "leverage", "best practice",
  "robust". Sempre "veloce", "sicuro", "verificato".
- **Professionalità nei contenuti**: ogni numero ha la fonte (file,
  riga, query SQL); ogni configurazione ha l'esempio testato; ogni
  comando bash funziona se incollato.

---

## 2. Indice gerarchico (mandatorio)

Il manuale ha **questa** struttura, in **questo** ordine. Non
inventare sezioni nuove, non scambiare l'ordine.

```
0. Prefazione — chi è CARA, perché esiste, a chi serve
1. Architettura
   1.1 Vista d'insieme (diagramma)
   1.2 Stack tecnologico
   1.3 Container Docker
   1.4 Rete (proxy-net, IP statici, porte)
   1.5 Storage (Postgres, Redis, MinIO, ChromaDB, filesystem)
   1.6 Data flow di una richiesta chat (sequenza completa)
2. Setup ambiente di sviluppo
   2.1 Prerequisiti hardware (NanoPC-T6 o equivalente)
   2.2 Prerequisiti software (Docker, Python, Node)
   2.3 Clone + venv + dipendenze
   2.4 .env e variabili
   2.5 Avvio docker compose
   2.6 Migration database (Alembic)
   2.7 Bootstrap admin
   2.8 Test che l'installazione funzioni
3. Struttura del repository
   3.1 Albero delle directory commentato
   3.2 Convenzioni di codice (Python + TypeScript)
   3.3 Branch, commit, tag, releases
4. Backend — moduli profondi
   4.1 cara.config — Settings via Pydantic
   4.2 cara.store — engine + sessionmaker SQLAlchemy
   4.3 cara.models — ogni modello ORM, riga per riga
   4.4 cara.api.v1 — ogni router, ogni endpoint, request/response
   4.5 cara.api.deps — dipendenze FastAPI (auth, get_session)
   4.6 cara.services — servizi singoli, uno per uno
   4.7 cara.ai — LLM, embeddings, NER, OCR, TTS, KV cache
   4.8 cara.cda — Content Discovery Agent
   4.9 cara.core — state machine + bus
   4.10 cara.integrations — Google, Telegram
   4.11 cara.learning — episodic, semantic, habits, reflective, tool_metrics
   4.12 cara.router — Pipeline + Stage Protocol
   4.13 cara.skills — Skill Factory (primitive, registry, dispatcher)
   4.14 cara.smarthome — abstraction + HA adapter + NLU
   4.15 cara.widgets — Wallet engine + catalog
   4.16 cara.workflows — Receipt, Bill, Recipe + auto-confirm
5. Frontend — moduli profondi
   5.1 Stack (React 18, Vite, Tailwind, vite-plugin-pwa)
   5.2 Routing (App.tsx + AppShell)
   5.3 Design system (tokens, componenti, icone)
   5.4 API clients (cara/frontend/src/api/*)
   5.5 Voce e audio (Web Speech, Piper TTS, WebAudio queue)
   5.6 Service worker e offline queue
   5.7 PWA install + manifest + shortcuts
6. AI / LLM
   6.1 Modello Qwen 2.5-1.5B w8a8 hybrid-0.5
   6.2 RKLLM runtime v1.1.0 (NPU RK3588)
   6.3 KV cache (prompt cache reuse)
   6.4 Sampling (temperature, top_p, top_k, repeat_penalty)
   6.5 System prompt (base + tone + facts)
   6.6 Modalità: fast (1.5B) vs quality (3B)
   6.7 LoRA fine-tune (dataset + RunPod)
7. Voce, TTS, STT
   7.1 Piper TTS (voci, normalizzatore anglicismi)
   7.2 Sentence streaming + audio_chunk SSE
   7.3 Whisper STT lato server
   7.4 Web Speech API lato client
   7.5 Wake word
8. Memoria
   8.1 Episodic (events table)
   8.2 Semantic (facts + embeddings + retrieval top-k)
   8.3 Estrazione automatica vs pin manuale
   8.4 GDPR export e purge
9. Skill Factory
   9.1 Cosa è una skill (esempio JSON commentato)
   9.2 Primitive registrate (catalogo)
   9.3 Executor: come una skill viene eseguita passo passo
   9.4 Dispatcher Tier-1/2/3
   9.5 Skill Author (cloud LLM, Phase D)
   9.6 Aggiungere una primitive nuova (tutorial)
   9.7 Aggiungere una skill nuova (tutorial)
10. Wallet & widgets
   10.1 Engine + Protocol Widget
   10.2 Catalogo dei 13 widget
   10.3 Layout per surface (mobile/wall/watch/...)
   10.4 Preset profili (parent/teen/child/elder)
   10.5 Aggiungere un widget nuovo
11. Proattività
   11.1 Engine (priority, cooldown, silent hours)
   11.2 RuleContext (cosa una rule può leggere)
   11.3 Le 10 rules concrete
   11.4 Aggiungere una rule
12. Smart home
   12.1 Abstraction layer (Protocol)
   12.2 HomeAssistant REST adapter
   12.3 HomeAssistant WebSocket events
   12.4 NLU 4-stadi
   12.5 Permessi per ruolo
   12.6 Aliases device
13. CDA — Content Discovery Agent
   13.1 Architettura (orchestrator + provider + verifier)
   13.2 Search providers (SearXNG, DuckDuckGo)
   13.3 Discovery per tipo (article, podcast, video, audio_stream, ...)
   13.4 KB persistente
   13.5 Confidence + decay
14. Workflow
   14.1 Pattern unificato classify/extract/propose/execute
   14.2 ReceiptWorkflow
   14.3 BillWorkflow
   14.4 RecipeWorkflow
   14.5 Auto-confirm trust streak
15. Multi-device
   15.1 Modello Device + surface_class
   15.2 Pairing flow (codice 6 cifre + Redis ticket)
   15.3 Pagina /pair (lato dispositivo)
   15.4 Pannello /admin/devices
16. Integrazioni Google
   16.1 OAuth flow (PKCE, scope set)
   16.2 Calendar sync (pull + push)
   16.3 Gmail readonly garantito (4 livelli)
   16.4 Email NLU 3-livelli
17. Notifiche e bus famiglia
   17.1 Web Push (VAPID, AES-GCM)
   17.2 Family bus (Redis pub/sub, WebSocket)
   17.3 Topic e payload
18. Setup wizard (`/setup`)
   18.1 Quando parte e perché
   18.2 Gli 8 step
   18.3 Reset e riconfigurazione
19. Sicurezza
   19.1 JWT (access, refresh, device)
   19.2 AES-GCM per OAuth tokens
   19.3 Cert TLS (mkcert + Let's Encrypt)
   19.4 Audit log (cosa viene loggato)
   19.5 Mascheramento secret nei log
20. Pannello admin
   20.1 /admin (dashboard)
   20.2 /admin/skills, /memory, /smart-home, /proactivity, /devices, /diagnostics
   20.3 Settings (ogni flag spiegato)
21. Diagnostica e debug
   21.1 Sysadmin dashboard
   21.2 Diagnostics suite
   21.3 Debug overlay (Ctrl+Shift+D)
   21.4 Log structlog (formato e filtri)
22. Test
   22.1 Unit (in-memory SQLite)
   22.2 Smoke (httpx vs live backend)
   22.3 Playwright E2E
   22.4 CI / GitHub Actions (futuro)
23. Deploy
   23.1 docker compose --profile app build
   23.2 Migration in produzione
   23.3 Restart senza downtime (limiti)
   23.4 Rollback
24. Manutenzione
   24.1 Backup Postgres
   24.2 KV cache cleanup
   24.3 Pulizia voci anglicismi runtime
   24.4 Aggiornamento modello LLM
25. Estendere CARA (tutorial pratici)
   25.1 Aggiungere un endpoint REST
   25.2 Aggiungere un widget
   25.3 Aggiungere una rule proattiva
   25.4 Aggiungere una primitive skill
   25.5 Aggiungere una migration Alembic
26. Riferimento variabili .env (tabella)
27. Riferimento admin_settings (tabella)
28. Riferimento API REST (Swagger)
29. Riferimento WebSocket (family_bus)
30. Glossario
31. Troubleshooting
   31.1 LLM non si carica
   31.2 TTS muto
   31.3 PWA non si installa
   31.4 OAuth Google fallisce
   31.5 Push notifications non arrivano
   31.6 Backend si riavvia in loop
32. Cambia-log + roadmap futura
```

Ogni sezione di livello 1 inizia con una **sintesi di 3 righe** ("Cosa
copre questa sezione, perché ti serve, in 30 secondi cosa imparerai").
Ogni sezione di livello 2 ha un **mini-indice** delle sotto-sezioni.

---

## 3. Stile di scrittura — regole non negoziabili

### 3.1 Frasi
- Massimo 25 parole per frase.
- Una idea per frase.
- Niente subordinate annidate. Spezza in due frasi.
- Voce attiva sempre. "Postgres conserva gli eventi", non "gli eventi
  vengono conservati da Postgres".

### 3.2 Paragrafi
- Massimo 4-5 frasi.
- Inizio sempre con la **conclusione** o la **definizione**, poi i
  dettagli. ("La KV cache evita di ricalcolare il prefisso del prompt
  ad ogni turno. Funziona così: ...")
- Nessun "introduce", "rappresenta", "è un sistema che" — descrivi
  cosa fa, non cosa è.

### 3.3 Termini tecnici
- Quando appare per la prima volta, **defini** il termine in una riga.
  Esempio: "*KV cache* — la memoria che il modello tiene durante la
  generazione, riutilizzabile fra turni successivi della stessa
  conversazione."
- Le sigle si **espandono** la prima volta: "Pubblica/Sottoscrittore
  (pub/sub)", "Identità federata (OAuth)".
- Glossario alla fine raccoglie tutti i termini.

### 3.4 Esempi di codice
- Sempre **funzionanti** (incollabili in shell o file). Mai
  pseudo-codice.
- Sempre con **percorso file completo**: `cara/api/v1/setup.py:120`.
- Commenti **in italiano**, codice in inglese (è la convenzione
  CARA).
- Output atteso mostrato sotto il blocco codice, formato:
  ```
  $ comando
  output qui
  ```

### 3.5 Diagrammi
- Mermaid quando possibile (rendono in markdown senza tool extra):
  ```
  ```mermaid
  flowchart LR
    Browser -->|HTTPS| nginx-proxy
    nginx-proxy --> cara-frontend
    nginx-proxy --> cara-backend
  ```
  ```
- Per architettura più complessa: PNG salvato in
  `docs/manual/diagrams/<sezione>.png`, alt text descrittivo.

### 3.6 Callouts
Tre tipi standard, sempre nello stesso formato Markdown:

```markdown
> **💡 Suggerimento** — usa `make logs-backend` invece di
> `docker logs cara-backend` per evitare di battere ogni volta.

> **⚠️ Attenzione** — la migration `c8a7d94e1f02` non è reversible:
> testa il rollback su un ambiente staging prima.

> **🔒 Sicurezza** — non loggare mai il `password_hash` in chiaro.
> Usa `mask_secret()` da `cara/services/env_writer.py`.
```

Niente altri tipi di callout. Niente emoji decorative oltre a queste
tre.

---

## 4. Screenshot e immagini di riferimento

Il manuale deve avere **screenshot dove rendono più facile capire** —
specialmente per le pagine UI (admin, setup wizard, wallet, login,
debug overlay). Le sezioni elencate qui sotto **richiedono** uno
screenshot:

| Sezione | Screenshot richiesto |
|---|---|
| 1.1 | Diagramma architettura (Mermaid o PNG) |
| 1.6 | Sequence diagram di una chat (Mermaid) |
| 5.3 | Mostra il design system: paletta colori day/night fianco a fianco |
| 7.3 | Forma d'onda / spettrogramma di una sintesi Piper |
| 9.2 | Schermata `/admin/skills` con lista skill |
| 9.5 | Schermata Skill Author dialog |
| 10.4 | Wallet con i 4 preset, uno screenshot per preset |
| 12.5 | Tabella permessi per ruolo (può essere screenshot di codice o tabella markdown) |
| 15.3 | Pagina `/pair` con codice 6 cifre |
| 15.4 | Pagina `/admin/devices` con un device pendente |
| 16.1 | Flow OAuth Google (sequence diagram) |
| 18.2 | **8 screenshot**, uno per step del wizard |
| 19.3 | Schermata cert installato (Chrome lock chiuso) |
| 20.1 | Dashboard `/admin` |
| 21.3 | Debug overlay aperto |
| 23.3 | Output di `docker compose ps` con tutti i container healthy |

### 4.1 Standard tecnici per gli screenshot

- **Formato**: PNG, max 1920×1080, **niente** JPG.
- **Cartella**: `docs/manual/img/<sezione>-<slug>.png`.
  Esempio: `docs/manual/img/18-2-step-1-admin.png`.
- **Naming**: `<numero-sezione>-<numero-sotto>-<slug-kebab>.png`.
- **Risoluzione device**: desktop 1280×800 di default; mobile screens
  390×844 (iPhone 14).
- **Tema**: scegli il tema della UI in base al contesto: passi notturni
  → night mode; passi diurni → day mode. Specifica nella didascalia.
- **Anonimizzazione**:
  - Mai email reali oltre a quelle dei test (`pedotoa@gmail.com` è OK
    perché documentata in CLAUDE.md, oppure
    `pw-<random>@example.com`).
  - Mai token, password, API key visibili — riempi con `xxxxxxxx…`
    nello screenshot, blur i campi password.
  - Mai IP pubblici esterni (mascher con `xxx.xxx.xxx.xxx`).
  - L'IP LAN `192.168.1.23` è OK (è documentato in CLAUDE.md).
- **Cursore e cornici**: niente cursore mouse, niente cornici browser
  (Chrome bookmarks bar nascosti).
- **Lingua UI**: italiano.

### 4.2 Inserimento nei capitoli

Ogni screenshot ha:

```markdown
![Step 1 del setup wizard, modulo crea-amministratore con i campi
email, nome completo, password, fuso orario.](img/18-2-step-1-admin.png)

*Figura 18.1 — Step 1 del wizard. I campi obbligatori sono evidenziati
in verde. La data di nascita è opzionale ma alimenta la rule
`birthday_today`.*
```

Alt text **sempre** descrittivo (per accessibilità + per chi legge il
manuale stampato).

### 4.3 Come catturare gli screenshot

Per il setup wizard (sezione 18) bisogna fare un reset:

```bash
# Login + reset
TOK=$(curl -sk -X POST https://192.168.1.23:8455/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"pedotoa@gmail.com","password":"caracasa2026"}' \
  | jq -r .access_token)
curl -sk -X POST -H "Authorization: Bearer $TOK" \
  https://192.168.1.23:8455/api/v1/setup/reset

# Apri /setup in browser, naviga gli 8 step facendo screenshot
```

Per gli admin pages, basta loggarsi come Antonio e visitare le route.
Lo scrittore tecnico **dovrebbe** prendersi un'ora per produrre tutti
gli screenshot in una passata, salvandoli in
`docs/manual/img/raw/`. Poi li ottimizza (vedi §4.4) e li sposta in
`docs/manual/img/`.

### 4.4 Ottimizzazione

Ogni PNG va passato attraverso `pngquant` per ridurre dimensione
mantenendo qualità:

```bash
pngquant --quality=80-95 --force --ext .png docs/manual/img/*.png
```

Target: nessuna immagine > 200 KB.

---

## 5. File layout

Il manuale vive in `/opt/cara/docs/manual/` strutturato così:

```
docs/manual/
├── README.md                # questo è l'INDICE — punto di entry
├── 00-prefazione.md
├── 01-architettura.md
├── 02-setup-ambiente.md
├── 03-struttura-repo.md
├── 04-backend-moduli.md     # diviso in sub-files se >2000 righe
│   ├── 04-01-config.md
│   ├── 04-02-store.md
│   └── ...
├── 05-frontend-moduli.md
├── 06-ai-llm.md
├── 07-voce-tts-stt.md
├── 08-memoria.md
├── 09-skill-factory.md
├── 10-wallet-widgets.md
├── 11-proattivita.md
├── 12-smart-home.md
├── 13-cda.md
├── 14-workflow.md
├── 15-multi-device.md
├── 16-integrazioni-google.md
├── 17-notifiche-bus.md
├── 18-setup-wizard.md
├── 19-sicurezza.md
├── 20-pannello-admin.md
├── 21-diagnostica-debug.md
├── 22-test.md
├── 23-deploy.md
├── 24-manutenzione.md
├── 25-estendere-cara.md
├── 26-env-vars.md
├── 27-admin-settings.md
├── 28-api-rest.md
├── 29-websocket.md
├── 30-glossario.md
├── 31-troubleshooting.md
├── 32-changelog-roadmap.md
├── img/                     # tutti gli screenshot
│   ├── raw/                 # versione non ottimizzata (gitignored)
│   ├── 01-architettura.png
│   ├── 09-2-skills-list.png
│   └── ...
└── diagrams/                # PNG generati da Mermaid
    └── 01-1-stack.png
```

Il `README.md` di `docs/manual/` è l'**indice** completo, con link a
ogni sezione e un breve abstract per ognuna. Ogni file contiene la sua
sezione **autoportante** (un lettore può leggere solo il capitolo 9 e
capirlo, con i giusti rimandi a definizioni in altri capitoli).

---

## 6. Convenzioni Markdown

- **Heading**: solo `#` (titolo file), `##` (sezioni 1.x), `###`
  (1.x.y). Mai `####` o più profondo — segno che la struttura è
  sbagliata, spezza in più sezioni.
- **Codice inline**: backtick singoli per percorsi, comandi corti,
  nomi di funzione. `cara/api/v1/setup.py`, `flush_all()`,
  `docker compose up -d`.
- **Codice in blocco**: tre backtick + linguaggio (`python`, `bash`,
  `typescript`, `sql`, `yaml`, `mermaid`). **Mai** blocchi senza
  linguaggio.
- **Tabelle Markdown**: per riferimenti densi (env vars, settings,
  endpoint). Allinea le colonne dei separatori.
- **Liste numerate** per sequenze ("fai questo, poi questo"). Liste
  con bullet per insiemi senza ordine.
- **Link interni**: relativi (`[capitolo 9](09-skill-factory.md)`),
  mai assoluti.
- **Cross-reference** alle righe di codice: `cara/file.py:123` (line
  number). Aggiorna se il codice si sposta — vedi §9.

---

## 7. Profondità per ogni capitolo

Ogni capitolo deve coprire questi 5 livelli, in ordine:

1. **Cosa**: definizione di cosa fa il modulo / la funzione, in 1-3
   righe.
2. **Perché**: motivazione di design (perché esiste, quale problema
   risolve).
3. **Come**: spiegazione tecnica con file/funzione/riga + esempio
   funzionante.
4. **Come testarlo**: comando o test che il lettore può eseguire per
   vedere il modulo in azione.
5. **Come estenderlo**: tutorial passo-passo per aggiungere una
   variante (sezione "Estendere CARA" capitolo 25 raccoglie i tutorial
   completi; ogni capitolo singolo ha la versione corta).

Se manca anche solo uno di questi livelli, la sezione **non è
completa**.

---

## 8. Cross-referencing

Ogni concetto importante (KV cache, router pipeline, primitive,
skill, surface, fact, episodic event, family bus, audit log, ...)
deve avere:

1. **Una definizione canonica** in una sezione (la "casa"). Esempio:
   "KV cache" è definita in 6.3.
2. **Una entry nel glossario** (cap 30) che rimanda alla sezione
   canonica.
3. **Tutti i riferimenti successivi** linkano alla sezione canonica
   (`Vedi [6.3 KV cache](06-ai-llm.md#kv-cache)`).

Mai duplicare la spiegazione completa: ripeti solo l'essenziale e
linka.

---

## 9. Sincronizzazione col codice

Il manuale **invecchia rapido** se non c'è disciplina. Per ridurre il
debito:

- Ogni esempio di codice ha un commento `# verificato 2026-MM-DD` se
  copiato da un file specifico, così si capisce quando è stato
  l'ultima volta verificato.
- Ogni numero di linea (`cara/api/v1/setup.py:120`) che appare nel
  manuale viene **regenerato** ogni release con uno script che
  l'autore del manuale **deve includere** (vedi §11).
- Il manuale ha un proprio CHANGELOG: `docs/manual/CHANGELOG.md`. Ogni
  PR che modifica `cara/*` o `frontend/src/*` significativamente deve
  aggiornare la sezione del manuale corrispondente nel medesimo PR
  (regola implicita, non bloccante).

---

## 10. Definition of Done

Il manuale è "fatto" quando:

1. ✅ Esistono tutti i file in §5.
2. ✅ Il `README.md` indice elenca tutte le 32 sezioni con abstract.
3. ✅ Ogni sezione di livello 1 ha la "sintesi 30 secondi" iniziale.
4. ✅ Ogni screenshot della §4.1 è presente, ottimizzato, con alt
   text e didascalia.
5. ✅ Tutti i comandi bash riportati funzionano se incollati.
6. ✅ Tutti gli esempi Python/TS compilano (per il TS, il manuale
   passa `tsc --noEmit` su una cartella di esempi se necessario).
7. ✅ Il glossario contiene almeno 40 voci.
8. ✅ Il troubleshooting contiene almeno 6 scenari realistici con
   diagnostica + risoluzione.
9. ✅ Ogni capitolo passa la **review di leggibilità**: un lettore
   non-CARA-pratico legge il capitolo, riassume in 3 frasi cosa ha
   imparato, e quelle 3 frasi corrispondono all'intento del capitolo.
10. ✅ Il manuale completo PDF (generato con pandoc, vedi §11) è
    leggibile su tablet 10" (font ≥ 11pt, nessun overflow).

---

## 11. Tooling consigliato

### 11.1 Generazione PDF

```bash
cd docs/manual
pandoc \
  README.md 00-*.md 01-*.md 02-*.md ... 32-*.md \
  -o cara-manuale-programmatore.pdf \
  --pdf-engine=xelatex \
  --toc --toc-depth=3 \
  -V mainfont="Source Serif Pro" \
  -V monofont="JetBrains Mono" \
  -V geometry:margin=2cm \
  -V lang=it \
  --highlight-style=tango
```

### 11.2 Lint markdown

```bash
npx markdownlint-cli2 'docs/manual/**/*.md'
```

Ignora la regola "no-trailing-punctuation" sui titoli (italiano usa
"?" nei titoli).

### 11.3 Rigenera line numbers

Crea `docs/manual/scripts/refresh_linerefs.py` che:

1. Estrae tutti i pattern `cara/[^ ]+\.py:\d+` o
   `frontend/src/[^ ]+\.tsx?:\d+` dai .md.
2. Per ognuno, controlla se la linea è ancora valida (apre il file,
   verifica che il contenuto matchi un commento canonico tipo
   `# DOC-REF: kv-cache.flush_all`).
3. Aggiorna il numero di linea nel .md se il file ha riorganizzato.

Senza questo script, in 6 mesi metà dei riferimenti del manuale sono
sbagliati.

### 11.4 Screenshot pipeline

```bash
docs/manual/scripts/take-screenshots.sh
```

Bash che:

1. Risetta lo stato del sistema (admin, settings, alcune skills demo).
2. Apre Chromium headless con Puppeteer / Playwright.
3. Naviga ogni route richiesta e salva il PNG in `img/raw/`.
4. Esegue `pngquant` su tutti i raw e li sposta in `img/`.

Lo script è **opzionale** — il manuale può anche essere costruito a
mano la prima volta. Diventa essenziale dalla seconda iterazione.

---

## 12. Anti-pattern (non fare)

1. **Non riscrivere il codice nel manuale**. Il manuale **spiega** il
   codice, non lo duplica. Citalo con percorso/riga.
2. **Non scrivere "ovviamente", "semplicemente", "facilmente"**.
   Niente è ovvio per il lettore esterno.
3. **Non usare GIF animate**. Pesanti, accessibilità zero. Sequenza di
   PNG numerati se serve mostrare un flow.
4. **Non scrivere TODO o FIXME nel testo finale**. Se una sezione non
   è pronta, segnala in `CHANGELOG.md` del manuale, non nel corpo.
5. **Non tradurre nomi di funzione/variabili/file in italiano**.
   `getCurrentUser()` resta `getCurrentUser()`.
6. **Non usare prima persona singolare ("io ho deciso...")**. Usa la
   forma impersonale ("CARA usa...") o la seconda persona diretta
   ("vedi, configura, modifica").
7. **Non usare formule magiche tipo "best practice", "industry
   standard", "robust", "scalable"**. Sostituisci con la cosa
   concreta che intendi.
8. **Non includere screenshot di sistemi terzi senza permesso** (es.
   GitHub, Google Cloud Console). Sostituisci con frecce annotate o
   descrizione testuale.
9. **Non includere segreti negli screenshot** anche solo "scaduti". Lo
   schema di anonimizzazione di §4.1 è non negoziabile.
10. **Non superare 500 righe per file `.md`**. Spezza in sub-files
    (`04-01-config.md`, `04-02-store.md`, ...).

---

## 13. Effort + delivery

| Fase | Effort |
|---|---|
| Schema + indice + README | 0.5 EW |
| Capitoli 1-3 (architettura, setup, repo) | 1 EW |
| Capitoli 4-5 (backend + frontend deep) | 2-3 EW |
| Capitoli 6-17 (singole feature) | 4 EW |
| Capitoli 18-25 (admin/test/deploy/extension tutorials) | 2 EW |
| Capitoli 26-32 (riferimenti + glossario + troubleshooting) | 1 EW |
| Screenshot + ottimizzazione | 1 EW |
| Review + leggibilità + tool scripts | 1 EW |
| **Totale** | **~12-13 EW** |

**Rilascio incrementale**: ogni capitolo è leggibile in autonomia.
Pubblica il README + capp 1-3 dopo una settimana, capp 4-9 dopo due,
e così via. Ogni rilascio è una PR sul ramo `epic-13-manual` con
screenshot + caps inclusi.

**Tag finale**: `manual-v1.0.0` quando tutti i punti DoD §10 sono
verdi. La versione del manuale segue **separatamente** il SemVer di
CARA (es. CARA è a v1.1.0, manuale può essere a manual-v0.4.0).

---

## 14. Note di consegna

Apri un branch `epic-13-programmer-manual`. Un commit per capitolo
finito. Mai un commit con "[WIP]" o "draft". Ogni commit lascia il
manuale in stato leggibile.

Quando dai questo prompt a un agente:

- Il file è il prompt completo, niente altro contesto serve.
- L'agente **deve** seguire l'indice §2 senza deviare.
- L'agente **deve** rispettare lo stile §3.
- L'agente **deve** produrre gli screenshot della §4 (o lasciare un
  placeholder testuale `<<screenshot: descrizione di cosa fotografare>>`
  che lo scrittore tecnico umano riempirà dopo).
- Se l'agente ha dubbi su cosa è effettivamente implementato in CARA,
  apre `cara/<modulo>/*.py` e legge il codice; **non inventa**.
- Se l'agente trova un'incongruenza fra codice e prompt, **chiede
  prima di scrivere**.

Buon lavoro.
