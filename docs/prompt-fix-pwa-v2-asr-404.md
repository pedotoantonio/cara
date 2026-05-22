# Prompt — Fix "ASR failed: HTTP 404" PWA v2 (microfono)

> Bug report dell'utente: dopo aver registrato via microfono dal browser
> nella PWA v2, l'app risponde "Qualcosa è andato storto / ASR failed:
> HTTP 404". Bug analizzato, causa identificata, fix professionale
> applicato. Questo documento serve sia come post-mortem sia come
> prompt riutilizzabile per chi dovesse risolvere bug simili.

**Versione**: 1.0 — 2026-05-22
**Bug ID**: pwa-v2-asr-404
**Severity**: Bloccante (voice flow inutilizzabile)
**Branch**: `feature/pwa-v2`

---

## 1. Sintomo

Riprodotto dall'utente su `https://192.168.1.23:8456/`:

1. Apre il VoicePanel (dal CTA "Parla con me" della Hub Casa o dal
   long-press sul FloatingAvatar)
2. Concede il permesso microfono se non già concesso
3. Parla per qualche secondo
4. VAD stop o tap "Ho finito"
5. Il pannello mostra "Qualcosa è andato storto"
6. Sotto, in piccolo: `ASR failed: HTTP 404`

I log nginx del container `cara-frontend-v2` mostrano:
```
"POST /api/v1/asr?language=it HTTP/1.1" 404 22
```

Il container `cara-backend` non vede mai il request: nginx lo proxa
correttamente, ma FastAPI risponde 404 perché il path non matcha
nessun route registrato.

## 2. Root cause

Discrepanza tra **path che il client chiama** e **path che il backend
espone**.

### 2.1 Cosa il client chiama

In `frontend-v2/src/api/asr.ts`:

```ts
export async function transcribeBlob(blob: Blob, language = 'it') {
  const r = await authFetch(`/asr?language=...`, { method: 'POST', body: fd });
  ...
}
```

Dato che `API_BASE = '/api/v1'`, il request finale è
`POST /api/v1/asr?language=it`.

### 2.2 Cosa il backend espone

In `backend/cara/api/v1/asr.py`:

```python
router = APIRouter(prefix="/asr", tags=["asr"])

@router.post("/transcribe")          # ← path corretto!
async def transcribe(...): ...
```

Il `prefix="/asr"` + `@router.post("/transcribe")` produce il path
finale **`POST /api/v1/asr/transcribe`**.

Anche la Wall surface ha lo stesso pattern: `POST /api/v1/wall/asr`
(che a sua volta proxa internamente a `asr_svc.transcribe_bytes`).

### 2.3 Perché è successo

Ho scritto `api/asr.ts` assumendo che il router fosse esposto come
flat `/asr` senza ulteriore path. Ho dato per scontato — invece di
verificare contro l'OpenAPI live `/api/openapi.json` o leggere il
file backend `asr.py`. **L'unico passo di prevenzione che sarebbe
servito.**

### 2.4 Perché non l'ho beccato nei test

I miei smoke test `curl` colpivano `GET /api/v1/auth/me`,
`GET /api/v1/tasks`, `POST /api/v1/conversations`, ma NON ho fatto
test funzionale di `/api/v1/asr/transcribe` con un blob audio reale
— solo verifica che la routing frontend renderizzi (la VoicePanel
appare ma esegue il request al backend solo al click di "Ho finito",
non al mount).

---

## 3. Fix

Cambio in **`frontend-v2/src/api/asr.ts`**:

```diff
- const r = await authFetch(`/asr?language=${encodeURIComponent(language)}`, {
+ const r = await authFetch(`/asr/transcribe?language=${encodeURIComponent(language)}`, {
    method: 'POST',
    body: fd,
  });
```

Una sola riga. Nessuna modifica al backend, nessuna nuova migration,
niente schema TypeScript da cambiare — il `AsrResult` ritornato resta
identico (text + confidence_label + sanity + no_speech_prob + ...).

---

## 4. Verifica end-to-end

```bash
TOKEN=$(curl -sk -X POST https://192.168.1.23:8456/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"pedotoa@gmail.com","password":"caracasa2026"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 1. Endpoint sbagliato (il bug) → 404
curl -sk -X POST "https://192.168.1.23:8456/api/v1/asr?language=it" \
  -H "Authorization: Bearer $TOKEN" \
  -F "audio=@/path/to/test.webm" \
  -w "  bad endpoint: HTTP=%{http_code}\n" -o /dev/null

# 2. Endpoint corretto → 200 con JSON sanity check
curl -sk -X POST "https://192.168.1.23:8456/api/v1/asr/transcribe?language=it" \
  -H "Authorization: Bearer $TOKEN" \
  -F "audio=@/path/to/test.webm" \
  -w "  fixed endpoint: HTTP=%{http_code}\n"
```

Acceptance: il bottone "Parla con me" sulla Hub Casa, registrare 2
secondi di parlato, stop automatico VAD → vedere il transcript
mostrato nel VoicePanel, **niente messaggio di errore**.

---

## 5. Prevenzione (lezione operativa)

### 5.1 Validare gli endpoint contro l'OpenAPI live PRIMA di scrivere il client

Quando il backend è già in produzione, il source-of-truth è lo schema
OpenAPI. La PWA v2 lo serve a `/api/openapi.json` (dev) — basta una
query veloce:

```bash
curl -sk https://192.168.1.23:8456/api/openapi.json \
  | python3 -c "
import sys, json
spec = json.load(sys.stdin)
for path, ops in spec.get('paths', {}).items():
    for method in ops:
        if method in {'get', 'post', 'put', 'patch', 'delete'}:
            print(f'{method.upper():6} {path}')
" | sort
```

Output canonico — copia-incollalo dentro un `// REFERENCE` block in
testa al file API client mentre lo scrivi. Niente assumere.

### 5.2 Smoke test funzionale, non solo "200 OK"

I test che ho scritto nel `pwa-v2-test-report-2026-05-22.md` colpivano
ogni endpoint con un `GET` o `POST` con body vuoto e verificavano
`HTTP=200`. Non bastano: per `/asr` serviva un POST multipart con
un blob audio reale (anche silenzio sintetico va bene). Aggiungere
al test suite:

```bash
# Genera 1 secondo di silenzio webm/opus
ffmpeg -f lavfi -i anullsrc=r=16000:cl=mono -t 1 -c:a libopus /tmp/silence.webm

# Test ASR endpoint
curl -sk -X POST "https://192.168.1.23:8456/api/v1/asr/transcribe?language=it" \
  -H "Authorization: Bearer $TOKEN" \
  -F "audio=@/tmp/silence.webm" \
  | python3 -m json.tool
```

Aggiungere lo stesso pattern per ogni endpoint multipart o
non-trivial (file upload `/files`, push `/push/subscribe`,
`/voice/synthesize`).

### 5.3 Aggiungere "endpoint fingerprint" al boot della PWA

Estensione futura: al boot dell'app, fare un fetch a un manifest
client che elenca gli endpoint che ci aspettiamo, e fare un HEAD
veloce a ognuno. Se uno è 404, mostra un warning in dev console
("La PWA si aspettava `POST /asr/transcribe` ma 404"). Una sorta di
linter di runtime per il client-vs-backend contract.

Non urgente per ora, ma utile quando il backend evolve velocemente
e i client devono adeguarsi.

---

## 6. Cosa NON è successo (e perché)

- **NON è un problema di nginx reverse-proxy**: il request arriva
  correttamente da `cara-frontend-v2` a `cara-backend:8000`. nginx
  fa il suo lavoro.
- **NON è un problema di CORS**: stessa origine, niente preflight.
- **NON è un problema di auth**: il Bearer token c'era e funzionava
  per altri endpoint.
- **NON è un problema del backend**: il backend è invariato dalla
  v1, FastAPI funziona perfettamente. È il client v2 che cerca un
  path che non esiste.

Lezione meta: quando vedi 404 da un endpoint API, la prima cosa da
controllare è il path effettivo, non assumere "ah forse manca
autorizzazione" o "ah forse il backend non gira" — la console di
rete del browser ti dà subito la verità.

---

## 7. Status post-fix

- ✅ `frontend-v2/src/api/asr.ts` aggiornato (1 riga cambiata)
- ✅ `npm run build` verde
- ✅ Container `cara-frontend-v2` rebuildato + ridistribuito
- ✅ Test funzionale verificato: ASR ora 200, transcript reso correttamente
- ✅ Commit + push su `feature/pwa-v2`

Tempo totale dal bug report al fix in produzione: ~10 minuti.

---

## Appendice — Lista degli endpoint API che la PWA v2 chiama

Per riferimento futuro, ecco l'inventario completo:

```
GET    /api/v1/auth/me
PATCH  /api/v1/auth/me
POST   /api/v1/auth/login
POST   /api/v1/auth/lan-login
POST   /api/v1/auth/refresh
POST   /api/v1/auth/change-password

GET    /api/v1/chat/health
POST   /api/v1/chat?conversation_id=...                  (SSE)
GET    /api/v1/conversations
POST   /api/v1/conversations
GET    /api/v1/conversations/{id}/messages
DELETE /api/v1/conversations/{id}

POST   /api/v1/asr/transcribe?language=...               (← bug qui)

GET    /api/v1/tasks
POST   /api/v1/tasks
PATCH  /api/v1/tasks/{id}
DELETE /api/v1/tasks/{id}

GET    /api/v1/shopping
POST   /api/v1/shopping
PATCH  /api/v1/shopping/{id}
DELETE /api/v1/shopping/{id}
POST   /api/v1/shopping/clear-bought

GET    /api/v1/notes
POST   /api/v1/notes                                     (body, non content!)
PATCH  /api/v1/notes/{id}
DELETE /api/v1/notes/{id}

GET    /api/v1/reminders/upcoming?days=&limit=
POST   /api/v1/reminders/{id}/done
POST   /api/v1/reminders/{id}/snooze

GET    /api/v1/persona/me
POST   /api/v1/persona/me/rebuild
DELETE /api/v1/persona/me

GET    /api/v1/memory/facts
DELETE /api/v1/memory/facts/{id}
POST   /api/v1/memory/export
POST   /api/v1/memory/purge

GET    /api/v1/wallet/layout?surface=
GET    /api/v1/wallet/presets
GET    /api/v1/widgets/render?ids=

GET    /api/v1/weather/current?lat=&lon=
GET    /api/v1/weather/forecast?lat=&lon=&days=

GET    /api/v1/news?limit=

GET    /api/v1/events?start=&end=

GET    /api/v1/proposals
POST   /api/v1/proposals/{id}/accept
POST   /api/v1/proposals/{id}/reject

GET    /api/v1/devices
POST   /api/v1/devices/pair-start
DELETE /api/v1/devices/{id}

GET    /api/v1/diagnostics

GET    /api/v1/cda/items?kind=&active_only=
POST   /api/v1/cda/items/{id}/feedback

GET    /api/v1/integrations/google/status
GET    /api/v1/oauth/google/start
POST   /api/v1/integrations/google/disconnect
POST   /api/v1/integrations/google/sync

GET    /api/v1/admin/settings                            (admin only)

GET    /api/v1/push/public-key
POST   /api/v1/push/subscribe
DELETE /api/v1/push/subscribe
```

Se uno di questi ritorna 404 nella v2 in futuro, è probabile lo
stesso bug pattern: il client v2 e il backend hanno divergenze sul
path. Confrontare prima con `/api/openapi.json`.
