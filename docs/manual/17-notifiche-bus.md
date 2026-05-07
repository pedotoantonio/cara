# Cap 17 — Notifiche e bus famiglia

> *Sintesi 30 secondi.* Due meccanismi paralleli. **Push web (VAPID)**
> manda notifiche a un singolo telefono anche quando il browser è
> chiuso. **Family bus (Redis pub/sub + WebSocket)** sincronizza i
> device aperti in tempo reale (chiunque crea una task, gli altri
> la vedono apparire). Entrambi opt-in, entrambi rispettano silent hours.

## 17.1 Differenza fra push e bus

| | Push web (VAPID) | Family bus (WS) |
|---|---|---|
| Triggerato da | Server (scheduled, evento) | Server (CRUD, eventi) |
| Riceve | Service worker dei device subscribed | Tab/PWA aperte attualmente |
| Quando | Anche con browser chiuso | Solo se l'utente ha la pagina aperta |
| Permission | OS lo chiede esplicitamente | Nessuna, subscribe via WS |
| Scopo | Reminder, allerte importanti | Sync UI (live update task list) |
| Costo | Più "intrusivo" — vibrazione, badge | Invisibile, aggiorna UI silenziosamente |

CARA usa entrambi insieme: una task aggiunta su iPhone fa
**bus → tutte le tab aperte aggiornano** + **push → wall e tablet
non aperte mostrano badge**.

## 17.2 Web Push (VAPID) — `cara.services.push`

**Voluntary Application Server Identification for Web Push**: spec W3C
per push notifications dal proprio server senza dipendere da Apple/Google
(per device collegati).

### Setup chiavi

Una coppia di chiavi VAPID per server. Il setup wizard step 6c
genera in automatico:

```bash
# Output del wizard, salvato in .env
VAPID_PUBLIC_KEY=BMXyz...86char-base64
VAPID_PRIVATE_KEY=hQz...44char-base64
VAPID_SUBJECT=mailto:antonio@example.com
```

Senza queste 3 variabili, il push scheduler **non parte** al boot. Log:
`cara.push_scheduler_skipped reason=vapid_not_configured`.

### Subscribe — frontend

`frontend/src/lib/push.ts`:

```typescript
export async function subscribeToPush(): Promise<PushSubscription | null> {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return null;

  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: VAPID_PUBLIC_KEY,
  });

  // Manda al backend per registrare
  await authFetch('/api/v1/push/subscribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(sub.toJSON()),
  });

  return sub;
}
```

Il browser mostra il prompt OS "permettere notifiche da CARA?". Se
accetta, `pushManager.subscribe` ritorna un `PushSubscription` con
`endpoint` (URL specifico FCM/Apple Push) + `keys.auth` + `keys.p256dh`.
Backend salva in `push_subscriptions`.

### Send — backend

`cara.services.push:send_to_user`:

```python
from cara.services.push import PushPayload, send_to_user

await send_to_user(
    session, user_id=user.id,
    payload=PushPayload(
        title="CARA — promemoria",
        body="Bolletta luce in scadenza domani",
        icon="/icon-192.png",
        url="/tasks?id=abc",
        tag="reminder.bolletta.123",
    ),
)
```

Il backend:
1. Carica tutte le `PushSubscription` di quell'user
2. Per ognuna: cifra il payload con la sua `p256dh+auth`, manda al
   suo `endpoint` (FCM, APNs, ecc.)
3. Errore 410 (Gone) → cancella la subscription dal DB
4. Errore 404, 403, 500: log + retry futuro

### Push scheduler — `services/push_scheduler.py`

Loop ogni 60 secondi:

```python
async def _tick(sessionmaker):
    async with sessionmaker() as session:
        # Trova task con due_at fra now e now+5min
        # E reminded_at IS NULL (non ancora notificate)
        soon = await find_due_tasks(session)
        for task in soon:
            await send_to_user(session, task.user_id, PushPayload(
                title="CARA — promemoria",
                body=task.title,
                url=f"/tasks?id={task.id}",
                tag=f"task.due.{task.id}",
            ))
            task.reminded_at = datetime.now(timezone.utc)
        await session.commit()
```

Cosi le task con `due_at` ricevono push 5 minuti prima.

Se l'utente cambia `due_at`, `reminded_at` si resetta e il push
ri-fira al nuovo orario.

### Endpoints REST

**File**: `cara/api/v1/push.py`.

```
POST /push/subscribe          - registra subscription utente
DELETE /push/subscribe/{id}    - cancella
GET /push/subscriptions       - lista (l'utente vede le sue)
POST /push/test               - manda push di test (admin)
```

## 17.3 Family bus — `cara.services.family_bus`

**File**: `cara/services/family_bus.py`.

Pub/sub via Redis: ogni evento è un messaggio JSON pubblicato su un
channel `cara:family:default`. I subscriber sono i WebSocket connessi.

### Pubblicare — backend

```python
from cara.services.family_bus import publish

await publish(
    kind="task.created",
    user_id=user.id,
    payload={"id": str(task.id), "title": task.title},
)
```

Fire-and-forget. Errori Redis swallowed (il pub/sub è "nice to have",
non critico).

### Subscriber — `cara/api/v1/family_ws.py`

WebSocket endpoint `/api/v1/family/ws?token=<jwt>`:

1. Verifica JWT (può essere user o device token)
2. `await pubsub.subscribe("cara:family:default")`
3. Loop: per ogni messaggio Redis, send al client come JSON

```python
@router.websocket("/ws")
async def family_ws(ws: WebSocket, token: str):
    user_id = verify_jwt(token)
    await ws.accept()
    pubsub = redis.pubsub()
    await pubsub.subscribe("cara:family:default")
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            data = json.loads(message["data"])
            await ws.send_json(data)
    finally:
        await pubsub.unsubscribe()
```

### Frontend — `lib/familySync.ts`

```typescript
import { onFamilyEvent, type FamilyEvent } from '@/lib/familySync';

useEffect(() => {
  const unsub = onFamilyEvent('task.created', (e: FamilyEvent) => {
    refetchTasks();  // re-load la lista
  });
  return unsub;
}, []);
```

Il modulo gestisce reconnect on disconnect, exponential backoff,
sub/unsub multipli senza aprire WS multiple.

### Topic standard

| Topic | Quando |
|---|---|
| `task.created`, `task.updated`, `task.deleted`, `task.completed` | CRUD task |
| `shopping.added`, `shopping.bought`, `shopping.cleared` | CRUD spesa |
| `note.created`, `note.deleted` | CRUD note |
| `proposal.new` | Email scanner ha trovato un'email |
| `chat.turn` | Qualcuno sta chattando in casa |
| `setup.completed` | Wizard finito (refresh UI) |

### Filtering per utente

I topics non hanno filtro for-user di default — ogni messaggio va
a tutti. Il client filtra:

```typescript
onFamilyEvent('task.created', (e) => {
  if (e.user_id !== currentUserId) {
    // Mostra toast: "Sara ha creato una task"
  }
  refetchTasks();
});
```

Per privacy estrema (es. teen non vede note del child), si può
aggiungere `target_user_id` al payload e filtrare server-side. Non
implementato oggi.

## 17.4 Sicurezza + privacy

### Push

- **VAPID**: il subscription endpoint contiene un token specifico per
  device + il public key del server. Il push **non può** essere
  inviato da un altro server (la firma VAPID viene verificata)
- **Payload cifrato**: AES-128-GCM con `p256dh + auth` keys derivate
  dal device. Solo quel device può decifrare
- **Niente PII**: il payload contiene title + body brevi, mai password
  o tokens

### Family bus

- **JWT verifica**: WS rifiuta connessioni senza token valido
- **Niente cross-family**: oggi tutti gli utenti CARA sono famiglia
  unica (`channel="default"`). In futuro multi-famiglia, il channel
  sarà per-family
- **Niente body sensibili**: gli eventi family bus contengono solo
  ID + minimi metadati (es. `task.created` ha id + title, non
  description completa)

> **⚠️ Attenzione** — il family bus è "diffuse a tutti i device".
> Se un device cade in mani esterne, vede tutti gli eventi della
> casa fino a quando non lo deauthenticano. Disabilita rapidamente
> via `/admin/devices`.

## 17.5 Silent hours per push

Il push scheduler rispetta le silent hours dell'engine proattività
(default 22:00-07:00):

- Priority `URGENT` passa sempre
- `HIGH/MEDIUM/LOW` muted in finestra silenziosa

Per ruolo:
- `child`: niente push dopo 21:00 (anche URGENT)
- `teen`: niente push dopo 22:00 (eccetto URGENT vere emergenze)

Configurazione globale in `admin_settings.silent_hours_start` /
`silent_hours_end` (default `22` / `7`).

## 17.6 Test push manuale

Per verificare che la pipeline funzioni:

```bash
# Login admin
TOK=$(curl -sk -X POST https://192.168.1.23:8455/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"pedotoa@gmail.com","password":"caracasa2026"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Push di test al proprio utente
curl -sk -X POST -H "Authorization: Bearer $TOK" \
  https://192.168.1.23:8455/api/v1/push/test
```

Output: il device subscribed riceve push "CARA — test" entro pochi
secondi.

## 17.7 Errori comuni

| Sintomo | Causa | Risoluzione |
|---|---|---|
| Subscribe ritorna `null` | Browser non supporta o utente ha negato | iOS Safari: serve PWA installata; Chrome: chiedi di nuovo dal banner |
| Push non arriva | Subscription scaduta (410) | Re-subscribe dal frontend |
| Bus WS non si connette | Token scaduto | Refresh JWT, re-open WS |
| Bus eventi vecchi al re-connect | Pub/sub Redis non persiste | Atteso — pub/sub è "live only", se sei offline ti perdi gli eventi |
| Push duplicati su update | Backend non aggiorna `reminded_at` | Bug — verifica il flow scheduler |

## 17.8 Estendere — push notification custom

Vuoi mandare un push quando arriva un'email speciale (proposta).

```python
# Già esiste, esempio:
from cara.services.push import send_to_user, PushPayload

if proposal.confidence > 0.85:
    await send_to_user(
        session, user_id=user.id,
        payload=PushPayload(
            title="CARA — proposta dall'email",
            body=f"{sender}: {proposal.subject}",
            icon="/icon-192.png",
            url=f"/me/proposte?id={proposal.id}",
            tag=f"proposal.{proposal.id}",
        ),
    )
```

`tag` è importante: device push API merge notifiche con stesso tag
(non si accumulano). Buono per rate limiting "una per topic".

## 17.9 Estendere — bus topic custom

Vuoi una notifica "arrivato pacco" via webhook esterno (DPD, GLS).

**1. Backend**: aggiungi un endpoint webhook + pub:

```python
# cara/api/v1/webhooks.py
@router.post("/webhooks/parcel/{user_id}")
async def parcel_arrived(user_id: int, body: ParcelArrival):
    # Verify webhook signature (esercizio per il lettore)
    await family_bus.publish(
        kind="parcel.delivered",
        user_id=user_id,
        payload={"carrier": body.carrier, "tracking": body.tracking},
    )
    # Optional anche push diretto
    await send_to_user(session, user_id, PushPayload(
        title="📦 Pacco arrivato",
        body=f"{body.carrier}: {body.tracking}",
    ))
    return {"ok": True}
```

**2. Frontend**: subscribe al topic:

```typescript
useEffect(() => {
  return onFamilyEvent('parcel.delivered', (e) => {
    showToast(`Pacco ${e.payload.carrier} arrivato`);
  });
}, []);
```

---

[← Cap 16 Integrazioni Google](16-integrazioni-google.md) · [README](README.md) · [Cap 18 Setup wizard →](18-setup-wizard.md)
