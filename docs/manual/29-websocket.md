# Cap 29 — Riferimento WebSocket

> *Sintesi 30 secondi.* CARA ha un solo endpoint WebSocket:
> `/api/v1/family/ws?token=<jwt>`. Subscribe al family bus Redis,
> riceve eventi JSON in tempo reale (task.created, shopping.added,
> proposal.new, ecc.). Non c'è autenticazione cookie — il JWT va in
> querystring.

## 29.1 Endpoint

```
WS  wss://192.168.1.23:8455/api/v1/family/ws?token=<JWT>
```

Il JWT può essere:
- **Access token utente** (Bearer) — accesso normale
- **Device token** — la wall in cucina senza login user esplicito

Entrambi accettati dalla dependency JWT verifier. Verifica:

```python
async def family_ws(ws: WebSocket, token: str):
    try:
        user_id = verify_jwt(token)
    except ValueError:
        await ws.close(code=4001)
        return
    await ws.accept()
    # ... subscribe Redis pub/sub
```

Codice di errore close:
- `4001` = token invalido o assente
- `4003` = token utente disabilitato/cancellato
- `1011` = errore server

## 29.2 Formato messaggio

Server → client, sempre JSON object:

```json
{
  "kind": "task.created",
  "user_id": 1,
  "ts": "2026-05-07T14:32:01Z",
  "payload": {
    "id": "uuid",
    "title": "Test task"
  }
}
```

Campi standard:
- `kind` — dot-namespaced event type
- `user_id` — chi ha causato l'evento (per auto-filter local-echo)
- `ts` — timestamp ISO 8601 UTC
- `payload` — forma libera per topic, sempre JSON object

## 29.3 Topic standard

### Task

```
task.created      payload: {id, title, due_date}
task.updated      payload: {id, title, done, ...}
task.deleted      payload: {id}
task.completed    payload: {id, title}
```

### Shopping

```
shopping.added    payload: {id, title, qty}
shopping.bought   payload: {id, title}
shopping.cleared  payload: {count}
```

### Note

```
note.created      payload: {id, title}
note.deleted      payload: {id}
```

### Proposal (email)

```
proposal.new      payload: {id, sender, subject, kind}
proposal.accepted payload: {id, target_id}  # task/event creato
proposal.rejected payload: {id}
```

### Chat

```
chat.turn         payload: {conversation_id, user_id, tokens, ttft}
```

### Smart home (filtrato — solo eventi rilevanti)

```
smarthome.scene_activated  payload: {scene_id, name}
smarthome.lights_off_all  payload: {count}
```

### Setup

```
setup.completed   payload: {by_user_id}
```

### Proactivity

```
proactivity.suggestion  payload: {rule_id, text, priority, target_user_id}
```

## 29.4 Frontend client — `lib/familySync.ts`

```typescript
import { onFamilyEvent, openFamilySocket } from '@/lib/familySync';

// Apri la connessione (chiamato una volta in App.tsx)
useEffect(() => {
  return openFamilySocket();   // ritorna teardown
}, []);

// Subscribe a specifici topic
useEffect(() => {
  const unsub = onFamilyEvent('task.created', (e) => {
    console.log('new task:', e.payload.title);
    refetchTasks();
  });
  return unsub;
}, []);

// Wildcard
useEffect(() => {
  const unsub = onFamilyEvent('*', (e) => {
    console.log('any event:', e.kind);
  });
  return unsub;
}, []);
```

Il modulo gestisce:

- **Reconnect on disconnect**: WS chiusa → backoff esponenziale (2s,
  4s, 8s, max 30s) e ri-tenta
- **Single connection**: una sola WS per tab, multi-subscriber a
  topic
- **Auth refresh**: se 4001 (token scaduto), prova `auth.refresh()`
  e ri-apri WS

## 29.5 Backend pub — `cara.services.family_bus`

Per pubblicare un evento:

```python
from cara.services import family_bus

await family_bus.publish(
    kind="task.created",
    user_id=user.id,
    payload={"id": str(task.id), "title": task.title},
)
```

Internamente:
1. Costruisci messaggio `{kind, user_id, ts, payload}`
2. JSON-encode
3. `redis.publish("cara:family:default", json_str)`

Errori swallow (Redis offline → log warning, no throw).

## 29.6 Subscribe lato backend

L'endpoint `/family/ws` fa:

```python
import redis.asyncio as aioredis

async def family_ws(ws: WebSocket, token: str):
    user_id = verify_jwt(token)
    await ws.accept()

    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe("cara:family:default")

    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            data = json.loads(message["data"])
            await ws.send_json(data)
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe()
        await redis.close()
```

## 29.7 Filtering

Oggi tutti i topic vanno a tutti i subscriber. Il filtering è
client-side. Per filtering server-side (privacy stricter):

1. Aggiungi `target_user_id` al payload
2. WS subscriber: skip se `target_user_id != current_user_id` and
   `target_user_id is not None`

Non implementato. Per CARA single-family-trust è OK come è.

## 29.8 Debug WS

Apri DevTools → Network → WS:

```
ws://192.168.1.23:8455/api/v1/family/ws?token=...
↓ {"kind":"task.created","user_id":1,"ts":"...","payload":{...}}
↓ {"kind":"shopping.added",...}
```

Vedi messaggi in tempo reale. Filtra per kind se serve.

Da CLI:

```bash
# wscat (npm install -g wscat)
TOK=...
wscat -c "wss://192.168.1.23:8455/api/v1/family/ws?token=$TOK" \
  --no-check
# Connesso (premere CTRL+C per uscire)
```

Lasciatela aperta + crea una task da CARA UI in un'altra tab → vedi
l'evento arrivare.

## 29.9 Limitazioni

- **No durable**: pub/sub Redis non persiste. Se un client è offline,
  perde gli eventi del periodo offline. Riconnesso, vede solo eventi
  da quel momento in poi.
- **No replay**: non c'è meccanismo di "give me last N events". Per
  catch-up, il client fa un GET REST della risorsa ad apertura WS.
- **No partial failure**: se il backend pubblica `task.created` ma il
  WS è giù, il messaggio si perde. La fonte di verità resta sempre il
  DB → re-fetch su sync.

## 29.10 Topic personalizzati

Aggiungere un nuovo topic è banale:

```python
# In qualsiasi punto del backend
await family_bus.publish(
    kind="custom.my_event",
    user_id=user.id,
    payload={"key": "value"},
)
```

Frontend:

```typescript
onFamilyEvent('custom.my_event', (e) => {
  // ...
});
```

Convenzione naming: `<dominio>.<evento>` lowercase, snake_case.
Esempi: `task.created`, `family.bus.heartbeat`.

---

[← Cap 28 Riferimento API REST](28-api-rest.md) · [README](README.md) · [Cap 30 Glossario →](30-glossario.md)
