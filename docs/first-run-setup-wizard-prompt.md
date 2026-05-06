# CARA — First-Run Setup Wizard

**Tipo**: prompt di implementazione, da consegnare a Claude Code o a un
developer per la fase **post-installazione**.
**Scope**: una pagina/flow guidato che parte automaticamente al primo
boot di CARA, raccoglie tutti i parametri di configurazione critici,
li valida, li scrive nei posti giusti (`.env`, `admin_settings`,
`users`, certificati), e termina lasciando il sistema **pronto all'uso
dalla famiglia** senza che l'admin debba mai aprire un terminale.

Una buona installazione di CARA oggi richiede una decina di passaggi
manuali: bootstrap admin via CLI, generare VAPID keys, scrivere
`OAUTH_ENCRYPTION_KEY`, configurare HomeAssistant token, scegliere la
voce, ecc. Per la famiglia Pedoto questo non è un problema — Antonio
sa cosa fare. Per chiunque altro voglia usare CARA è un blocker. Il
wizard chiude questo gap.

---

## 1. Obiettivi

1. **Zero terminale**: un nuovo amministratore (con o senza esperienza
   tecnica) deve poter completare la configurazione **solo dal browser**.
2. **Resumable**: se chiude il wizard a metà, riprende da dove era.
3. **Self-test ad ogni step**: ogni parametro inserito viene verificato
   con una chiamata reale (es: il token HA è valido? la chiave VAPID è
   ben formata? l'API key Anthropic risponde?). Niente "configurato
   male, ce ne accorgiamo a runtime".
4. **Idempotente**: ri-eseguire il wizard non distrugge configurazioni
   esistenti — chiede prima conferma.
5. **Skip-friendly**: ogni passo opzionale è skippabile; CARA boota
   anche se solo lo step 1 è completato.
6. **Linguaggio italiano** in tutta la UI utente. Codice e commenti in
   inglese.
7. **Privacy by default**: feature flag esterni (`internet_enabled`,
   `cloud_llm_enabled`, `telegram_bot_enabled`) partono **OFF**;
   l'admin li attiva consapevolmente.

---

## 2. Quando il wizard parte

Il wizard appare a pieno schermo (route `/setup`) quando **tutte** le
seguenti condizioni sono vere all'avvio del frontend:

- `GET /api/v1/setup/status` ritorna `{ "completed": false }`
- Nessun utente con `is_admin=true` esiste in DB **OPPURE** la flag
  `setup_completed` in `admin_settings` è `false`/null

Una volta `setup_completed=true`, il wizard non riappare. È sempre
ri-eseguibile manualmente tramite `/admin/setup` (admin-only) per
re-configurare un parametro senza ricordarsi dove vive.

---

## 3. Struttura del wizard — 8 step

Ogni step è una pagina. Avanti / Indietro / Salta. Stato salvato
incrementalmente (vedi §6). Lo step **(★)** è obbligatorio; gli altri
sono skippabili con default ragionevoli.

### Step 1 — Admin & famiglia (★)

- Email amministratore (validazione formato + check unicità)
- Password (≥12 caratteri, mostrato indicatore di forza)
- Conferma password
- Nome completo
- Data di nascita (per il rule `birthday_today`)
- Fuso orario (default `Europe/Rome`, dropdown)

**Side effects**: crea l'utente con `is_admin=true`. Il sistema mints
JWT e proietta direttamente nel wizard step 2 con quel JWT in
localStorage — niente login intermedio.

### Step 2 — Sicurezza / TLS

Spiega in 3 righe perché serve un certificato fidato (per la PWA,
per evitare i warning sui device della famiglia).

Tre scelte:

1. **(default)** "Genera CA locale con mkcert" — esegue lato server
   `mkcert -install` (se non già fatto) + `mkcert <hostnames>` →
   sostituisce il cert nginx-proxy. Mostra il fingerprint SHA-256 e
   il QR di download della CA per Android/iPhone.
2. "Userò Let's Encrypt più tardi" — skip, tieni il self-signed.
3. "Ho già un cert mio" — upload file (cert + key, validato).

**Side effects**: file in `/opt/nginx-proxy/ssl/`, reload `nginx-proxy`.
Un endpoint dedicato (`POST /api/v1/setup/cert/regenerate`) serve la
operazione, audit-loggata.

### Step 3 — Identità famiglia

- Nome famiglia (es. "Famiglia Pedoto")
- Cognomi/nickname (CSV, popolano la family glossary del NER)
- Numero di membri previsto (1-12, slider)
- Lingua principale (default `it`, supporto `en` futuro)

**Side effects**: scrive in `admin_settings` (`family_name`,
`family_glossary`, `family_size`, `language`). Aggiorna
`cara.ai.ner.update_family_glossary()` runtime.

### Step 4 — Voce & lingua

Dropdown voci Piper (`GET /api/v1/voice/voices`). Auto-pre-seleziona
la voce italiana di default (`it_IT-paola-medium`).

Per ogni voce:

- Pulsante "Anteprima" → `POST /api/v1/voice/synthesize` con frase di
  esempio, riproduce audio inline
- Slider rate (0.5-2.0) / pitch (0.0-2.0) / volume (0.0-1.0)
- Toggle "Wake word 'CARA'" (default OFF — opt-in deliberato)
- Toggle "Streaming TTS" (default ON post-v1.0)

**Side effects**: scrive `voice_name`, `voice_rate`, `voice_pitch`,
`voice_volume`, `tts_streaming_enabled` in `admin_settings`.

### Step 5 — LLM & risposte

Sezione **base** sempre visibile:

- Modello (radio): "Veloce — 1.5B" (default) | "Qualità — 3B (più
  lento)". L'opzione 3B mostra un warning sulle ridotte performance
  sotto carico Frigate.
- Stile (tone preset): "Standard" | "Privacy" | "Giocoso".
- Max token risposta (slider 64–1024, default 512).

Sezione **avanzato** (collapsible, "Mostra opzioni avanzate"):

- System prompt custom (textarea, max 4000 char). Mostra il prompt
  default come placeholder.
- `validation_enabled` (toggle, default OFF, con warning "richiede
  modello 3B+, aumenta latenza").
- `cognitive_mode` (toggle, default OFF).

**Side effects**: scrive `llm_quality_mode`, `tone_preset`,
`llm_max_new_tokens`, `llm_system_prompt`, `validation_enabled`,
`cognitive_mode`. Flush della KV cache.

### Step 6 — Integrazioni casa (opzionale)

Quattro card affiancate, ognuna con toggle "Abilita":

#### 6a. HomeAssistant
- URL HA (default `http://172.31.0.1:8123`)
- Long-Lived Access Token (campo password)
- Pulsante **"Testa connessione"** → chiama `/api/states` su HA, mostra
  numero entità trovate. Fallisce → errore inline, blocca avanti.
- **Side effects**: scrive `smart_home_enabled`, `smarthome.ha_url`,
  `smarthome.ha_token` (cifrato AES-GCM via `OAUTH_ENCRYPTION_KEY`).

#### 6b. Frigate / Riconoscimento facciale
- URL Frigate (default `http://172.31.0.11:5000`)
- URL frigate-faces (default `http://192.168.1.23:8452`)
- Toggle `facial_recognition_enabled`
- **Side effects**: `frigate_url`, `frigate_faces_url`, `facial_recognition_enabled`.

#### 6c. Push notifications (VAPID)
- Pulsante **"Genera coppia di chiavi"** (server-side
  `py_vapid.Vapid01.generate_keys()`).
- Email per VAPID subject.
- **Side effects**: `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`,
  `VAPID_SUBJECT` in `.env`. Il push scheduler riavvia.

#### 6d. Telegram bot
- Toggle `telegram_bot_enabled` (default OFF).
- Bot token (campo password).
- Allowlist chat_id (lista, almeno 1 elemento se abilitato).
- Pulsante "Testa": il bot manda "/start configurazione OK" alla
  prima chat in allowlist.
- **Side effects**: `CARA_TELEGRAM_BOT_TOKEN`, `CARA_TELEGRAM_ALLOWED_CHAT_IDS`.

### Step 7 — Google + Cloud (opzionale)

#### 7a. Google Calendar/Gmail OAuth
- Spiegazione in 3 righe + link a "Come ottenere Client ID/Secret".
- Client ID
- Client Secret (campo password)
- Pulsante **"Genera chiave di cifratura"** → genera 32 byte random
  hex, scrive in `.env` come `OAUTH_ENCRYPTION_KEY` (richiede restart
  backend, mostrato come warning).
- Pulsante "Testa OAuth" → apre flow `/oauth/google/authorize` in
  popup, completa il consent, conferma callback.
- **Side effects**: `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`,
  `OAUTH_ENCRYPTION_KEY` in `.env`. Lifespan riavvia gli scheduler
  calendar/gmail.

#### 7b. Cloud LLM (Anthropic Haiku) — **DEFERRED**
Sezione mostrata ma con label "Sperimentale — disabilitata di
default":
- Toggle `cloud_llm_enabled` (default OFF).
- API key Anthropic (campo password, validato con un health-check call
  `messages.count_tokens` da 10 token).
- Toggle `skill_author_enabled` (richiede cloud_llm_enabled).
- **Side effects**: `ANTHROPIC_API_KEY` in `.env`, `cloud_llm_enabled`
  e `skill_author_enabled` in `admin_settings`.

### Step 8 — Privacy & feature flag globali

Una pagina di **summary** dei flag di alto livello con i loro default
ragionevoli pre-selezionati. L'admin scorre, vede cosa è ON e cosa è
OFF, eventualmente cambia.

| Flag | Default | Nota |
|---|---|---|
| `internet_enabled` | OFF | Master switch contenuti web |
| `news_enabled` | OFF | Richiede `internet_enabled=ON` |
| `radio_enabled` | OFF | Richiede `internet_enabled=ON` |
| `cda_enabled` | ON se `internet_enabled` | Discovery dinamica |
| `cda_safe_search_for_minors` | ON | Sempre on per teen/child |
| `proactive_suggestions_enabled` | OFF | Inizia silente, l'admin lo attiva quando si fida |
| `habit_learning_enabled` | OFF | Idem |
| `skill_dispatcher_tier2_enabled` | ON | Cosine matching skill |
| `skill_dispatcher_tier3_enabled` | OFF | LLM classifier (costoso) |
| `voice_recognition_enabled` | ON | Web Speech client-side |

**Definitive button**: "Termina configurazione". Scrive
`setup_completed=true` + `setup_completed_at=NOW()` + `setup_completed_by_user_id`.

---

## 4. Pagina di completamento

Schermata finale single-page:

- ✓ Cosa è stato configurato (lista verde).
- ⚠ Cosa rimane da fare manualmente (lista gialla — se ci sono passi
  che hanno avuto bisogno di restart, link al pulsante "Riavvia
  backend ora" che chiama `/admin/maintenance/restart`).
- 🔗 Link rapidi: "Vai alla home", "Aggiungi membri famiglia",
  "Configura primo dispositivo (`/admin/devices`)".
- Box "Promemoria sicurezza": ricorda di scaricare la CA su tutti i
  device — link a `http://<host>/cara-ca.crt`.

---

## 5. Backend — endpoint nuovi

Tutti sotto `/api/v1/setup` o `/api/v1/admin/setup`. Il primo step
è anonimo (nessun admin esiste ancora); gli altri richiedono il JWT
emesso allo step 1.

```
GET    /api/v1/setup/status               → { completed, current_step, version }
POST   /api/v1/setup/admin                → step 1 (anon)
POST   /api/v1/setup/cert/regenerate      → step 2 (admin)
POST   /api/v1/setup/cert/upload          → step 2 (admin, multipart)
POST   /api/v1/setup/family               → step 3 (admin)
POST   /api/v1/setup/voice                → step 4 (admin) — wraps admin_settings PATCH
POST   /api/v1/setup/llm                  → step 5
POST   /api/v1/setup/homeassistant/test   → 6a probe call
POST   /api/v1/setup/homeassistant        → 6a save
POST   /api/v1/setup/frigate              → 6b save
POST   /api/v1/setup/vapid/generate       → 6c key generation
POST   /api/v1/setup/vapid                → 6c save
POST   /api/v1/setup/telegram/test        → 6d ping
POST   /api/v1/setup/telegram             → 6d save
POST   /api/v1/setup/google               → 7a save
POST   /api/v1/setup/google/test          → 7a OAuth roundtrip
POST   /api/v1/setup/cloud                → 7b save
POST   /api/v1/setup/cloud/test           → 7b validate ANTHROPIC_API_KEY
POST   /api/v1/setup/feature-flags        → step 8
POST   /api/v1/setup/complete             → mark setup_completed=true
```

Tutti i save endpoint sono idempotenti, validano in-place, restituiscono
il nuovo stato.

### Schema persistenza

- Tabella `users` per l'admin.
- `.env` per: `JWT_SECRET` (auto-generato se mancante), `OAUTH_ENCRYPTION_KEY`,
  `GOOGLE_OAUTH_CLIENT_ID/SECRET`, `ANTHROPIC_API_KEY`, `VAPID_*`,
  `CARA_TELEGRAM_BOT_TOKEN`, `CARA_TELEGRAM_ALLOWED_CHAT_IDS`. Modifiche
  al `.env` richiedono restart backend (mostrato come banner permanente
  finché l'admin non clicca "Riavvia").
- `admin_settings` per tutti gli altri flag/preset.
- `setup_state` JSONB nuova chiave `admin_settings` per la persistenza
  intermedia del wizard (utile per il resume).

### Modifiche al `.env` da backend

Pattern: leggi il `.env` corrente, applica le mutazioni, riscrivi atomicamente
(scrivi su `.env.new`, `os.replace(.env.new, .env)`). Conserva commenti e
ordine. Trasporta i secret cifrati in transito (HTTPS) e mai loggati nel
audit log in chiaro — sostituisci con `***hash:<sha256[:8]>***`.

---

## 6. Frontend — design

- **Route esclusiva**: `/setup` — non ha la AppShell (che richiede
  utente loggato). Layout `<SetupShell />` con stepper top + footer
  Avanti/Indietro/Salta + body.
- **Stepper visivo**: 8 dot, dot completati verdi con check, corrente
  blu, futuri grigi.
- **Persistenza locale**: `localStorage["cara.setup.draft.v1"]` con i
  field non-secret dello step corrente (i secret restano in form, mai
  in localStorage).
- **Riavvio backend**: dopo step che mutano `.env`, mostra banner
  giallo persistente: "Servirà riavviare il backend a fine
  configurazione" + countdown + pulsante a fine wizard.
- **Errori inline**: ogni step mostra errori sotto al campo
  responsabile, mai banner globali "qualcosa è andato storto".
- **Tema**: usa il design system esistente (`design/tokens.ts`,
  `design/components/`). Day mode default per il setup (più
  professionale).

### Componenti nuovi

- `<SetupShell />` — layout con stepper.
- `<Step1Admin />` … `<Step8FeatureFlags />` — uno per step.
- `<SetupComplete />` — landing finale.
- `<TestableField />` — input + pulsante "Testa connessione" + stato
  pass/fail/loading. Riutilizzabile da HomeAssistant, Telegram,
  Google, Cloud.
- `<SecretField />` — input password con eye-toggle, mai dumped in
  console/log.

---

## 7. Sicurezza

- **Step 1 endpoint**: l'unico anonimo. Per evitare race admin-takeover,
  controlla `setup_completed=false` AND nessun utente `is_admin=true`
  prima di accettare. Se c'è già un admin, restituisce 403.
- **Audit log**: ogni step scrive un'entry `setup.step.<n>` con
  l'attore + IP + diff dei flag (i secret loggati come hash).
- **Rate limit**: max 5 tentativi `/admin` per IP / 5 minuti, max 20
  qualunque setup endpoint / 5 minuti.
- **Secret in transito**: HTTPS forzato (il setup wizard rifiuta di
  partire se `request.url.scheme != "https"` e `host != localhost`).
  Eccezione: il primissimo accesso può avvenire prima che il cert sia
  fidato → il wizard mostra una banner "Sei in HTTP non sicuro,
  completa lo step 2 (TLS) prima possibile".
- **Reset di emergenza**: CLI `python -m cara.bootstrap reset-setup`
  azzera `setup_completed` per re-aprire il wizard (non cancella
  utenti/dati, solo riapre la UI).

---

## 8. Test

### Backend smoke
- Tutti i 17 endpoint hanno test di auth (anon/non-admin/admin).
- Setup status iniziale → completed=false.
- Step 1 happy path → admin creato → JWT minted → setup_state aggiornato.
- Step 1 con admin esistente → 403.
- Step 6a HA test con URL irraggiungibile → 502 chiaro, non 500.
- Step 6c VAPID generate → due chiavi base64 ben formate, scritte in `.env`.
- Step 7b cloud test con API key invalida → 401 chiaro.
- Setup complete → `setup_completed=true` + audit entry.
- Re-trigger via `/admin/setup` da admin → idempotente, non resetta
  password, mostra valori correnti.

### Frontend E2E (Playwright)
- Boot fresh DB → atterra su `/setup` automaticamente.
- Compila step 1 → arriva su step 2.
- Indietro → step 1, valori persistono.
- Salta step opzionale 6 → step 7.
- Termina → `setup_completed=true` → next reload va su `/`.
- Re-apertura `/setup` con `setup_completed=true` → redirect a `/`.

### Definition of Done

1. ✅ 17 endpoint funzionanti + autenticati + auditati
2. ✅ 8 step UI + complete page, in italiano, accessibili (label
   associati, focus management ok)
3. ✅ Backend smoke tests verdi
4. ✅ Playwright happy-path verde
5. ✅ Manuale famiglia (`docs/MANUALE-FAMIGLIA.md`) aggiornato con un
   paragrafo "Primo accesso"
6. ✅ Manuale admin (`docs/MANUALE-ADMIN.md`) aggiornato con la
   sezione "Riconfigurazione via /admin/setup"
7. ✅ CHANGELOG.md → entry sotto `## [1.1.0]`
8. ✅ Su un host fresh (postgres + redis vuoti), un nuovo amministratore
   completa il wizard in <10 minuti **senza aprire un terminale**

---

## 9. Convenzioni CARA da rispettare (importanti)

- **Italian-first** in UI: Avanti, Indietro, Salta, Termina, Errore,
  Configurazione, Famiglia, Voce, ecc. Codice e commenti in inglese.
- **Pattern del repo**: rispetta le convenzioni di
  `cara/api/v1/admin.py` (Pydantic body schema, audit_svc.record,
  require_admin dep). Non duplicare DB I/O, riusa `admin_settings.set`.
- **Lifespan**: i scheduler che reagiscono ai flag (push, calendar,
  gmail, telegram, ha_events, proactivity) sono già gated all'avvio in
  `cara/main.py`. Non riscrivere — ragiona in termini di "scrivo il
  flag, restart il backend, lo scheduler riparte da solo".
- **Non re-implementare la CA generation**: usa lo stesso `mkcert`
  binary già installato (`/usr/local/bin/mkcert`). Lo step 2 invoca
  `mkcert ...` come subprocess, niente librerie crypto custom.
- **Zero plaintext secret nei log**: usa il logger structlog, mai
  `logger.info("anthropic_key=", key)`. Tutti i campi password hanno
  `logger.unbind`.
- **Cloud Haiku stays DEFERRED**: lo step 7b accetta input ma il flag
  `cloud_llm_enabled` parte sempre da OFF; l'admin deve attivarlo
  esplicitamente.
- **Path env var**: rispetta i nomi esistenti
  (`CARA_TELEGRAM_BOT_TOKEN`, non `TELEGRAM_TOKEN`; `OAUTH_ENCRYPTION_KEY`,
  non `OAUTH_KEY`).

---

## 10. Effort stimato

| Item | Effort |
|---|---|
| Backend endpoint + service + audit | ~2 EW |
| Frontend SetupShell + 8 step | ~3 EW |
| Step 2 cert mgmt (mkcert subprocess + upload) | ~0.5 EW |
| Step 6a/6c/6d test connections | ~0.5 EW |
| Step 7a OAuth integration test (popup roundtrip) | ~0.5 EW |
| Tests + docs | ~0.5 EW |
| **Totale** | **~7 EW** |

Si può rilasciare a scaglioni: prima Step 1+2+3+5+8 (core sufficiente
per boot), poi Step 4 (voce), poi 6+7 (integrazioni). Ogni release
incrementale è già un'app più usabile della precedente.

---

## 11. Cosa NON fare

- **Non** auto-aprire connessioni a `cloud.anthropic.com` finché
  l'admin non lo abilita esplicitamente nello step 7b.
- **Non** registrare il device pairing dentro il wizard — lo step 6
  finisce coi servizi, il pairing si fa **dopo** dal pannello admin
  (`/admin/devices`). Non confondere "admin/famiglia" con "device".
- **Non** chiedere parametri che CARA può scegliere da sola (numero
  worker uvicorn, redis URL, postgres URL: vivono in `.env` e li
  stabiliamo in fase di docker compose, non in fase di setup
  utente).
- **Non** scrivere migrazioni Alembic per `setup_state` se basta una
  chiave in `admin_settings` (è un dict JSON, perfetto per questo
  caso).
- **Non** riscrivere la `bootstrap.py` CLI — coesiste e rimane utile
  per recovery (`reset-setup`).

---

## 12. Note di consegna

Apri un branch `epic-12-setup-wizard`. Ogni step UI un commit.
Alla fine: tag `v1.1.0`, CHANGELOG.md aggiornato, demo gif del flow
completo nel README.

Quando lo dai a un agente: questo file è il prompt completo, niente
altro contesto serve. Se l'agente ha dubbi su comportamento di un
campo, l'agente chiede prima di indovinare.
