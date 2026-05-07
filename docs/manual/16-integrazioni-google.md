# Cap 16 — Integrazioni Google

> *Sintesi 30 secondi.* CARA si integra con Google Calendar (sync
> bidirezionale) e Gmail (read-only con estrazione automatica di
> appuntamenti/task). I token OAuth sono cifrati AES-GCM in DB. Per la
> Gmail, 4 livelli di garanzia che CARA non scriverà mai sulla casella
> di posta.

## 16.1 Architettura

```mermaid
flowchart LR
    User[Utente] -->|click 'Connetti Google'| Frontend
    Frontend --> CARA[/oauth/google/authorize]
    CARA -->|redirect 302| Google[Google OAuth]
    Google -->|callback con code| CARA
    CARA -->|exchange| Google
    CARA -->|access+refresh token| Encrypt[AES-GCM]
    Encrypt --> DB[(oauth_credentials)]

    Scheduler1[calendar_sync_loop] -->|every 5min| Calendar[Calendar API]
    Calendar -->|events| Sync[CalendarSync]
    Sync --> CalDB[(calendar_events)]
    Sync -->|link| Tasks[(tasks)]

    Tasks -->|on CRUD| Push[calendar_push]
    Push --> Calendar

    Scheduler2[gmail_scanner_loop] -->|every 10min| Gmail[Gmail API readonly]
    Gmail -->|messages| NLU[Email NLU 3-layer]
    NLU --> Proposals[(email_proposals)]
    Proposals -->|user accept| Tasks
```

## 16.2 OAuth flow — `cara.integrations.google_oauth`

**File**: `cara/integrations/google_oauth.py`.

Standard OAuth 2.0 Authorization Code Flow with PKCE.

### Setup admin

L'admin deve:

1. Andare su https://console.cloud.google.com/apis/credentials
2. Creare un nuovo OAuth 2.0 Client ID di tipo "Web application"
3. Aggiungere `https://192.168.1.23:8455/api/v1/oauth/google/callback`
   come authorized redirect URI
4. Salvare client_id + client_secret nel `.env` di CARA:
   ```
   GOOGLE_OAUTH_CLIENT_ID=...apps.googleusercontent.com
   GOOGLE_OAUTH_CLIENT_SECRET=...
   OAUTH_ENCRYPTION_KEY=<32-byte hex random>
   ```
5. Abilitare le API Google Calendar e Gmail nel proprio progetto
   Cloud Console
6. Restart `cara-backend` per leggere il `.env`

### Scope sets

`SCOPE_PRESETS` in `google_oauth.py`:

```python
SCOPE_PRESETS = {
    "calendar:rw": [
        "openid", "email",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.readonly",
    ],
    "gmail:ro": [
        "openid", "email",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.metadata",
    ],
}
```

L'utente sceglie quale scope set autorizzare. Calendar:rw permette
read+write; Gmail:ro **solo** read+metadata, niente send/modify.

### User flow

1. Utente clicca "Connetti Google Calendar" su `/me/integrazioni`
2. Frontend chiama `GET /oauth/google/authorize?scope_set=calendar:rw`
3. Backend genera URL autorizzazione + state token, redirect 302
4. Utente in Google: login + consenso
5. Google redirect a `/oauth/google/callback?code=...&state=...`
6. Backend exchange code → access_token + refresh_token
7. Backend salva in `oauth_credentials` (cifrato), redirect a
   `/me/integrazioni?status=connected`

## 16.3 Encryption — `cara.services.secrets`

**File**: `cara/services/secrets.py`.

I token OAuth sono dati sensibili. Vengono cifrati prima di entrare in
DB.

**Algoritmo**: AES-256-GCM con chiave globale `OAUTH_ENCRYPTION_KEY`
(32 byte hex in `.env`).

```python
from cara.services.secrets import encrypt, decrypt

cipher = encrypt("ya29.long-token-here")  # bytes opaque
plain = decrypt(cipher)                   # original string
```

Implementazione:
- Genera nonce random 12 bytes
- AES-256-GCM(plaintext, key, nonce)
- Output: `nonce + ciphertext + tag` (concatenated, base64-encoded)

`OAUTH_ENCRYPTION_KEY` viene caricata via `_key_bytes` lru_cache —
ricaricabile via `_key_bytes.cache_clear()` se ruoti la chiave.

> **🔒 Sicurezza** — la chiave vive solo in `.env` (non DB). Se perdi
> il file `.env`, perdi la possibilità di decifrare i token e ogni
> utente deve riautorizzare. Backuppalo a parte (es. password manager).

### Key rotation

Per ruotare la chiave senza invalidare tutto:

1. Genera nuova chiave
2. Cripta i token con la nuova, decripta con la vecchia (script in
   `scripts/rotate_oauth_key.py` — futuro)
3. Aggiorna `OAUTH_ENCRYPTION_KEY` in `.env`
4. Restart backend

## 16.4 Google Calendar — `cara.integrations.google_calendar`

**File**: `cara/integrations/google_calendar.py`. Wrapper su
`googleapiclient.discovery`.

### API esposte

```python
from cara.integrations.google_calendar import (
    list_calendars, list_events,
    insert_event, patch_event, delete_event,
    is_cara_managed,
)

# Lista calendari accessibili
calendars = await list_calendars(access_token)

# Eventi di un range
events = await list_events(
    access_token, calendar_id="primary",
    time_min=datetime.now(), time_max=datetime.now() + timedelta(days=30),
    sync_token="opt-incremental-sync-token",
)

# CRUD
ev_id = await insert_event(access_token, calendar_id="primary", body={...})
await patch_event(access_token, calendar_id, event_id, body={"summary": "..."})
await delete_event(access_token, calendar_id, event_id)
```

### `is_cara_managed`

Helper che controlla se un evento è stato creato da CARA. Lo facciamo
via `extendedProperties.private.cara_managed=1`. Cosi quando il pull
sync pesca un evento già nostro, lo salta e non genera echo.

```python
def is_cara_managed(event_dict) -> bool:
    return (
        event_dict.get("extendedProperties", {})
                  .get("private", {})
                  .get("cara_managed") == "1"
    )
```

### Calendar sync (pull) — `services/integrations/calendar_sync.py`

Loop ogni 5 minuti:
1. Per ogni utente con OAuth Calendar:
   - Decripta token, refresh se scaduto
   - `list_events(time_min=now, time_max=now+30d, sync_token=...)`
   - Per ogni evento NON cara_managed:
     - Upsert in `calendar_events` (link al `task` se titolo+data
       matchano un task esistente)
2. Salva il nuovo sync_token per la prossima iterazione

### Calendar push — `services/integrations/calendar_push.py`

Hooks fire-and-forget sui CRUD task. Quando l'utente crea un task con
`due_date`, il push:

1. `calendar_push.schedule_create(task)` — async, no block dell'utente
2. Costruisce body evento Calendar con `extendedProperties.private.cara_managed=1`
3. `insert_event(access_token, "primary", body)`
4. Salva `task.calendar_external_id = event_id` per future PATCH/DELETE

Ogni operazione è isolated: se Calendar è giù, l'errore viene loggato
ma il task rimane salvato.

> **💡 Suggerimento** — il marker `cara_managed=1` è la chiave per
> evitare il loop. Pull skip eventi con marker; push aggiunge marker.
> Cosi il task creato in CARA → eventoCalendar → CARA non lo ri-pesca.

## 16.5 Gmail — read-only garantito a 4 livelli

**File**: `cara/integrations/google_gmail.py`.

CARA legge le email per estrarre proposte di task/appuntamento. **Mai
scrive**, mai cambia il flag "letto", mai cancella, mai sposta.

Garanzia a 4 livelli:

### Livello 1 — OAuth scope

Solo `gmail.readonly` + `gmail.metadata`. Google rifiuta any
operazione di scrittura con HTTP 403, indipendentemente dal codice
CARA.

### Livello 2 — API surface

`google_gmail.py` esporta solo helper read-only:

```python
async def list_messages(...) -> list[Message]: ...
async def get_message(...) -> Message: ...
async def get_thread(...) -> Thread: ...
async def extract_text(...) -> str: ...
async def parse_headers(...) -> dict: ...
```

Non esistono `send_message`, `modify_message`, `trash_message` nel
modulo. Anche se un developer volesse, non può chiamarli (non sono
import).

### Livello 3 — Scanner

`gmail_scanner.py` usa solo questi helper. Non importa
`googleapiclient.discovery` direttamente, quindi non ha modo di
costruire client write.

### Livello 4 — Test di regression

`backend/tests/unit/test_gmail_readonly_guarantee.py` greppa i due
moduli per pattern proibiti:

```python
_FORBIDDEN_SUBSTRINGS = (
    "messages.modify", "messages.batchModify", "messages.trash",
    "messages.untrash", "messages.delete", "messages.send",
    "messages.batchDelete",
    "/modify", "/trash", "/untrash", "/batchModify",
    "/batchDelete", "/send",
    "removeLabelIds",
)
```

Se qualcuno aggiunge una di queste stringhe a `google_gmail.py` o
`gmail_scanner.py`, il test fallisce. Garanzia automatica nel CI.

> **🔒 Sicurezza** — il livello 4 è **non opzionale**. Se rimuovi il
> test, abbatti la garanzia. Mai disabilitarlo.

## 16.6 Email NLU — 3 layer

**File**: `cara/services/integrations/email_understanding.py`.

Quando arriva un'email, vogliamo sapere se contiene un appuntamento o
un task. Tre layer in cascata:

### Layer 1 — Regex deterministico (gratis)

Pattern italiani per:
- Data esplicita ("il 15 maggio", "lunedì 23")
- Ora esplicita ("alle 15:30", "h. 10")
- Verbi appuntamento ("appuntamento", "incontro", "visita medica")
- Verbi task ("rinnovare", "pagare entro", "scadenza")

Se uno di questi pattern matcha + è estraibile data/ora → genera
proposta `EmailProposal` con `confidence=0.7` e
`source_layer="layer1"`.

### Layer 2 — LLM locale (1.5B)

Se layer 1 non ha matchato (o ha bassa confidence), il backend invia
il body email al LLM con un prompt:

```
Ti do il testo di un'email. Rispondi solo "appointment" se contiene
un appuntamento con data/ora, "task" se contiene una scadenza/azione
da fare, "neither" altrimenti.

Email:
{body}

Risposta:
```

Costo: ~3 secondi NPU. Se risponde "appointment" o "task" + estrae
data/ora con un secondo prompt → confidence 0.6, source `layer2`.

### Layer 3 — Cloud Haiku (DEFERRED)

Per email ambigue dove layer 1+2 hanno bassa confidence, fallback a
Anthropic Haiku. **OFF di default** — l'admin deve abilitare via
`cloud_llm_enabled=true`.

Costo: ~$0.001 per email. Confidence 0.9, source `layer3`.

### Output

```python
class EmailProposal(Base):
    user_id: int
    gmail_message_id: str
    sender: str
    subject: str
    snippet: str          # primi 200 char
    proposal_kind: str    # "task" | "appointment"
    proposal_data: dict   # {title, due_at, description, ...}
    confidence: float
    source_layer: str     # "layer1" | "layer2" | "layer3"
    status: str           # "pending" | "accepted" | "rejected"
    created_at: datetime
```

L'utente vede le proposte su `/me/proposte` (UI: lista card con
"Accetta" / "Ignora").

### Trust streak per layer

`EmailLearningSignal` traccia accept/reject per (sender, kind).
Esempio: l'utente accetta tutto da `prenotazioni@dottore.it` →
confidence boost futuro per quel mittente.

## 16.7 Gmail scanner — `services/integrations/gmail_scanner.py`

Loop ogni 10 minuti:

```python
async def _scan_user(session, user_id):
    creds = await get_oauth_credentials(session, user_id, "gmail:ro")
    access_token = await get_access_token(creds)

    # Query restrittiva: solo email recenti, NON inviate, NON promo/social
    query = "newer_than:1d -in:sent -category:promotions -category:social"
    messages = await list_messages(access_token, query=query, max_results=20)

    for msg_meta in messages:
        # Skip se già processato
        if await already_processed(session, msg_meta.id):
            continue

        msg = await get_message(access_token, msg_meta.id)
        text = extract_text(msg)

        # NLU 3-layer
        proposal = await classify_email(text, sender=msg.headers.get("From"))
        if proposal is None:
            await mark_processed(session, msg_meta.id, no_proposal=True)
            continue

        await save_proposal(session, EmailProposal(
            user_id=user_id, gmail_message_id=msg_meta.id,
            sender=msg.headers["From"], subject=msg.headers["Subject"],
            snippet=text[:200],
            proposal_kind=proposal.kind, proposal_data=proposal.data,
            confidence=proposal.confidence, source_layer=proposal.layer,
            status="pending",
        ))

        # Family bus → frontend live
        await family_bus.publish("proposal.new", {...})
```

**Quota**: 20 email per utente per scan, max 1 scan per 10 min →
120 email/h max per utente. Ben sotto i quota Gmail (~10k requests/giorno).

## 16.8 Endpoint REST

**File**: `cara/api/v1/oauth.py`, `integrations.py`, `proposals.py`.

| Endpoint | Method | Cosa fa |
|---|---|---|
| `/oauth/google/status` | GET | Stato connessioni utente |
| `/oauth/google/authorize` | GET | Redirect a Google consent |
| `/oauth/google/callback` | GET | Google → CARA con code |
| `/integrations` | GET | Lista integrazioni configurate |
| `/integrations` | POST | Salva config integrazione |
| `/integrations/{provider}` | DELETE | Disconnect (revoke + cancella creds) |
| `/proposals` | GET | Lista email proposals utente |
| `/proposals/{id}/accept` | POST | Accetta → crea task/appuntamento |
| `/proposals/{id}/reject` | POST | Ignora → status=rejected |

## 16.9 UI utente — `/me/integrazioni` e `/me/proposte`

### `IntegrationsPage`

**File**: `frontend/src/routes/IntegrationsPage.tsx`.

Card per provider. Per Google:
- Badge "Connesso" / "Non connesso"
- Pulsante "Connetti Google Calendar" → redirect OAuth
- Pulsante "Connetti Gmail readonly" → redirect OAuth (scope diverso)
- BottomSheet calendar picker (quale calendario sincronizzare)
- Pulsante "Disconnetti"

### `ProposalsPage`

**File**: `frontend/src/routes/ProposalsPage.tsx`.

Lista card proposals. Per ogni proposal:
- Mittente + soggetto + snippet
- Tipo (task/appuntamento) + data estratta
- Pulsanti: **Accetta** (crea task/event), **Ignora** (rejected)

WebSocket subscribe a `proposal.new` → live update senza refresh.

## 16.10 Errori comuni

| Sintomo | Causa | Risoluzione |
|---|---|---|
| OAuth callback 400 "redirect_uri_mismatch" | URI in console.cloud.google diverso da CARA | Aggiungi exact URI `https://192.168.1.23:8455/api/v1/oauth/google/callback` |
| Token scaduto continuamente | refresh_token non salvato | Verifica che il consenso includa `prompt=consent` (per refresh_token) |
| Gmail scanner non trova nulla | Filtro query troppo restrittivo | Allenta `query` (es. `newer_than:7d`) |
| Calendar event duplicati | Pull non rispetta `cara_managed` | Verifica che push aggiunga `extendedProperties` correttamente |
| Cifratura fallisce ("nonce mismatch") | OAUTH_ENCRYPTION_KEY cambiata | Genera nuovi token oppure script rotation |

## 16.11 Privacy + retention

- Gmail body **non viene mai persistito**: solo `snippet[:200]` per
  contesto utente
- Calendar event mirrorati hanno solo summary + start/end + attendees
  (no description completa)
- `oauth_credentials` può essere cancellato dall'utente in qualsiasi
  momento via `DELETE /integrations/google` → revoke token via Google
  + cancella row
- Email scanner skip categorie `promotions` / `social` di default

> **🔒 Sicurezza** — se un utente lascia la famiglia o vuole revocare
> l'accesso, basta `DELETE /integrations/google`. Backend revoke i
> token via Google API + cancella oauth_credentials. Da Google Account
> → Permessi vede CARA come "removed".

---

[← Cap 15 Multi-device](15-multi-device.md) · [README](README.md) · [Cap 17 Notifiche e bus famiglia →](17-notifiche-bus.md)
