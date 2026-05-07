# Cap 18 — Setup wizard `/setup`

> *Sintesi 30 secondi.* Il setup wizard è una pagina a 8 step che porta
> un nuovo amministratore da "container booted" a "famiglia ready"
> senza terminale. Vive in `/setup` (anonimo per Step 1), persiste lo
> stato in `admin_settings.setup_state`, ed è ri-eseguibile da
> `/admin/setup` per riconfigurare.

## 18.1 Quando il wizard parte

Auto-redirect su `/setup` quando:
- `GET /api/v1/setup/status` ritorna `{completed: false}`
- E nessun admin esiste (per Step 1) OPPURE l'admin ha cliccato "Apri
  configurazione" da `/admin`

L'auth gate in `App.tsx` riconosce `/setup` come path anonimo
permesso (cap 5.2). Cosi un device fresh senza login può raggiungere
il wizard.

## 18.2 Gli 8 step

### Step 1 — Amministratore (★ obbligatorio)

```
- Email
- Nome completo
- Data nascita (per rule birthday_today)
- Password (≥12 char, indicator forza)
- Ripeti password
- Fuso orario (default Europe/Rome)
```

**Endpoint**: `POST /api/v1/setup/admin` (anonimo, single-shot).

Se non c'è admin → crea utente, mints JWT, salva in localStorage,
avanza a Step 2.

Se c'è già un admin → 403 con messaggio "esiste già un amministratore".
Step 1 mostra warning + chiede di fare login normale.

### Step 2 — Sicurezza / TLS

```
- Pulsante "Rigenera CA + cert"  → mkcert subprocess
- Pulsante "Salta"                → tieni self-signed
```

**Endpoint**: `POST /setup/cert/regenerate` o `/cert/skip`.

Se rigenera: chiama `mkcert -cert-file ... -key-file ... <hosts>` con
la lista SAN standard (192.168.1.23, 10.8.0.1, localhost, ecc.).
Mostra fingerprint SHA-256 + URL CA download. Restart nginx-proxy
necessario (manuale al momento — futuro: auto).

### Step 3 — Famiglia

```
- Nome famiglia (es. "Famiglia Pedoto")
- Nomi/cognomi separati da virgola/riga (NER glossary)
- Slider "Quanti siete?" (1-12)
- Lingua (default IT)
```

**Endpoint**: `POST /setup/family`.

Salva in `admin_settings.family_name`, `family_glossary`,
`family_size`, `language`. La family glossary aggiorna `cara.ai.ner`
runtime.

### Step 4 — Voce

```
- Voce Piper (default it_IT-paola-medium)
- Slider rate (0.5-2.0)
- Slider pitch (0-2)
- Slider volume (0-1)
- Toggle wake word (default OFF)
- Toggle TTS streaming (default ON)
```

**Endpoint**: `POST /setup/voice`.

Salva in `admin_settings`. Anteprima audio: il frontend chiama
`/voice/synthesize` con frase di esempio per testare la voce scelta.

### Step 5 — LLM

```
Base:
- Radio "Veloce 1.5B (raccomandato)" / "Qualità 3B (più lento)"
- Radio Tono "Standard / Privacy / Giocoso"
- Slider max tokens (64-1024, default 512)

Avanzate (collapsed):
- Textarea system prompt custom (vuoto = default)
- Toggle validation_enabled (richiede 3B+)
- Toggle cognitive_mode
```

**Endpoint**: `POST /setup/llm`.

Salva in `admin_settings`. Flush KV cache.

### Step 6 — Integrazioni casa

Quattro card affiancate, ognuna con toggle "Abilita":

**6a. Home Assistant**:
```
- URL (default http://172.31.0.1:8123)
- Token (campo password)
- Pulsante "Testa connessione"  → POST /setup/homeassistant/test
```

Probe: GET `<url>/api/states` con bearer → conta entità. Errori
strutturati (401 = token sbagliato, 502 = url irraggiungibile, ecc.).

**6b. VAPID push**:
```
- Email subject (opzionale)
- Pulsante "Genera coppia di chiavi"  → POST /setup/vapid/generate
```

Genera coppia VAPID lato server. Salva in `.env`. Mostra public key
prefix come conferma.

**6c. Telegram bot**:
```
- Bot token (campo password)
- Chat IDs allow (CSV)
```

Salva in `.env`.

**Endpoint**: `POST /setup/integrations/complete` quando finito.

### Step 7 — Google + Cloud

**7a. Google Calendar/Gmail**:
```
- Client ID
- Client Secret (campo password)
- Toggle "Genera chiave cifratura" (consigliato)
```

Salva in `.env` (`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`,
`OAUTH_ENCRYPTION_KEY`). Restart richiesto.

**7b. Cloud LLM (DEFERRED)**:
```
- Toggle Abilita (default OFF)
- API key Anthropic (campo password)
- Pulsante "Testa API key"  → POST /setup/cloud/test
- Toggle "Skill author" (richiede cloud abilitato)
```

`POST /setup/cloud/test` chiama `https://api.anthropic.com/v1/messages/count_tokens`
per verificare la key con costo zero (count_tokens è free).

**Endpoint**: `POST /setup/google` + `POST /setup/cloud`.

### Step 8 — Privacy / feature flags

10 toggle con help inline:

```
☐ internet_enabled               (master switch internet)
☐ news_enabled                    (richiede internet)
☐ radio_enabled                   (richiede internet)
☑ cda_enabled                     (discovery dinamica)
☑ cda_safe_search_for_minors    (sempre per teen/child)
☐ proactive_suggestions_enabled  (parte silente)
☐ habit_learning_enabled
☑ skill_dispatcher_tier2_enabled
☐ skill_dispatcher_tier3_enabled (LLM dispatcher, costoso)
☑ voice_recognition_enabled
```

Default conservative. L'admin attiva ciò che vuole.

**Endpoint**: `POST /setup/feature-flags` + `POST /setup/complete`.

## 18.3 State persistence — `setup_state`

In `admin_settings`:

```python
{
  "setup_state": {
    "completed": false,
    "current_step": "tls",
    "version": 1,
    "completed_steps": ["admin"],
    "completed_at": null,
    "completed_by_user_id": null,
    "env_dirty": true,         # se ha mutato .env (richiede restart)
    "cert_fingerprint": "..."
  }
}
```

Ad ogni step `_mark_step_completed()` aggiorna l'array. `current_step`
avanza al prossimo non completato.

## 18.4 Reset — riapertura wizard

L'admin esistente può riaprire il wizard via `POST /api/v1/setup/reset`.
Il reset:

1. `completed = false`
2. `completed_steps` mantiene "admin" (l'admin esiste, non si ricrea)
3. `current_step = tls` (parte da Step 2)

L'utente esistente quindi non è chiesto di registrarsi di nuovo —
il wizard parte direttamente da TLS.

## 18.5 Endpoints reference

**File**: `cara/api/v1/setup.py`. 18 endpoint:

| Endpoint | Method | Auth |
|---|---|---|
| `/setup/status` | GET | anon |
| `/setup/admin` | POST | anon (single-shot) |
| `/setup/cert/regenerate` | POST | admin |
| `/setup/cert/skip` | POST | admin |
| `/setup/family` | POST | admin |
| `/setup/voice` | POST | admin |
| `/setup/llm` | POST | admin |
| `/setup/homeassistant/test` | POST | admin |
| `/setup/homeassistant` | POST | admin |
| `/setup/vapid/generate` | POST | admin |
| `/setup/telegram` | POST | admin |
| `/setup/integrations/complete` | POST | admin |
| `/setup/google` | POST | admin |
| `/setup/cloud/test` | POST | admin |
| `/setup/cloud` | POST | admin |
| `/setup/feature-flags` | POST | admin |
| `/setup/complete` | POST | admin |
| `/setup/reset` | POST | admin |

## 18.6 UI — `SetupPage.tsx`

**File**: `frontend/src/routes/SetupPage.tsx`.

Architettura monolitica per atomicità di review: un solo file con
tutti gli 8 step come componenti interni + le primitive `Field`,
`CheckRow`, `PrimaryButton`.

**Layout**:

```
+------------------------------------------+
| HEADER                                   |
|   cara · setup       Passo X di 8      |
|   ●●●●●●○○ stepper                       |
+------------------------------------------+
| BODY (centered, max-w-2xl)              |
|   <h2>Nome del passo</h2>                |
|   [Step component dinamico]              |
+------------------------------------------+
| FOOTER                                   |
|   ← Indietro      I dati sono salvati...|
+------------------------------------------+
```

**Step navigation**: `next()` / `back()` mutano `stepIdx`. Lo step
chiamato `onDone()` per avanzare automaticamente al prossimo dopo
salvataggio.

**Persistence locale**: localStorage `cara.setup.draft.v1` per i
field non-secret così il refresh non perde input. I secret restano in
form, mai in localStorage.

## 18.7 Sicurezza

- **Step 1 endpoint**: l'unico anonimo. Refuses se admin esiste già →
  no race condition takeover
- **Audit log**: ogni step scrive `setup.step.<n>` con actor + IP +
  diff (secret → hash sha256[:8])
- **Secret in transito**: HTTPS forzato; sotto HTTP plain il wizard
  mostra un warning rosso "completa Step 2 prima possibile"
- **Reset CLI**: `python -m cara.bootstrap reset-setup` per recovery
  (azzera `setup_completed`, non cancella user/data)

> **🔒 Sicurezza** — il `setup_state` è in `admin_settings` quindi
> visibile a qualsiasi admin. Se hai più amministratori, vedono lo
> stato dello stesso wizard. Considera multi-tenant in futuro
> (chiave `setup_state` per family_id).

## 18.8 Restart `.env` — banner

Step 6c (VAPID), 6d (Telegram), 7a (Google), 7b (Cloud) mutano `.env`.
Pydantic-settings legge il `.env` SOLO al boot del backend. Quindi
finché non restart, le variabili non sono effettive.

Il wizard mostra un banner permanente "⚠ alcune modifiche richiedono
restart" finché `setup_state.env_dirty=true`. Al `/setup/complete`,
chiede conferma e (futuro) restart auto via `POST /admin/maintenance/restart`.

Oggi il restart è manuale:

```bash
docker restart cara-backend
```

## 18.9 Test wizard

Procedura per testare end-to-end:

```bash
# 1. Reset DB pulito
docker exec cara-postgres psql -U cara -d cara -c \
  "DELETE FROM users WHERE is_admin=true; \
   DELETE FROM admin_settings WHERE key='setup_state';"

# 2. Apri https://192.168.1.23:8455/setup nel browser
# 3. Compila Step 1, click "Crea amministratore"
# 4. Procedi step-by-step

# Verifica stato
curl -sk https://192.168.1.23:8455/api/v1/setup/status | jq

# Reset durante test
TOK=$(curl ... login)
curl -sk -X POST -H "Authorization: Bearer $TOK" \
  https://192.168.1.23:8455/api/v1/setup/reset
```

Coverage smoke: 8 test in `tests/smoke/test_setup_api.py` che provano
la status, la rifiutava admin-create con admin esistente, gli auth
gate, e i save round-trip.

## 18.10 Errori comuni

| Sintomo | Causa | Risoluzione |
|---|---|---|
| Step 1 non avanza | Validation password fallisce | Almeno 12 char, ripeti corrispondenti |
| `mkcert: command not found` | Binary non in PATH del container | mkcert vive sull'host, non nel container — restart manuale richiesto |
| `vapid/generate` fallisce | `pywebpush` mancante | Reinstalla: `pip install pywebpush>=2` |
| `homeassistant/test` 502 | URL HA irraggiungibile dal container | Verifica `network_mode: host` su HA + IP `172.31.0.1` |
| `cloud/test` 401 | API key invalida | Genera nuova chiave su console.anthropic.com |
| Wizard mostra "esiste admin" | Hai già un admin | Login normale, poi vai su `/admin/setup` |

---

[← Cap 17 Notifiche e bus](17-notifiche-bus.md) · [README](README.md) · [Cap 19 Sicurezza →](19-sicurezza.md)
