# Cap 12 — Smart home

> *Sintesi 30 secondi.* CARA controlla la casa tramite Home Assistant.
> Quando dici "accendi la luce del salotto", una NLU a 4 stadi capisce
> intent + entità + valore, controlla i permessi del tuo ruolo, e chiama
> il service HA. Subscribe alla WebSocket di HA per loggare ogni
> cambio di stato come `events`.

## 12.1 Astrazione — `cara.smarthome.base`

**File**: `cara/smarthome/base.py`.

CARA non parla direttamente con HA — parla con un Protocol astratto:

```python
class SmartHomeAdapter(Protocol):
    provider: str   # "ha" | "mqtt" | "shelly" | ...

    async def list_entities(self) -> list[Entity]: ...
    async def get_state(self, entity_id: str) -> EntityState | None: ...
    async def call_service(self, domain: str, service: str,
                          entity_id: str, params: dict) -> dict: ...
    async def list_areas(self) -> list[Area]: ...
    async def list_scenes(self) -> list[Scene]: ...
    async def health(self) -> HealthStatus: ...
    async def subscribe_events(self) -> AsyncIterator[StateChange]: ...
```

**Canonical entity id**: `<provider>:<local_id>`. Esempi:
- `ha:light.salotto`
- `mqtt:bagno/luce`
- `shelly:shellyplug-s/EAB78F`

Il prefisso provider permette adapter multipli senza collisioni.

**Capability vocabulary** (15 valori in `Capability` str-enum):

```
ON_OFF, BRIGHTNESS, COLOR, COLOR_TEMP, TEMPERATURE, HVAC_MODE,
FAN_MODE, OPEN_CLOSE, POSITION, TILT, LOCK_UNLOCK, PLAY_PAUSE,
VOLUME, SOURCE, SCENE_ACTIVATE, SCRIPT_RUN, AUTOMATION_TRIGGER
```

Le NLU (vedi 12.4) lavorano su queste capability cross-vendor.

## 12.2 HomeAssistant adapter — `cara.smarthome.homeassistant`

**File**: `cara/smarthome/homeassistant.py`.

L'adapter REST per HA. Configurato via:

```python
class HAConfig:
    base_url: str   # "http://172.31.0.1:8123" (HA in network_mode: host)
    token: str      # Long-Lived Access Token

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def ws(self) -> str:
        return self.base_url.replace("http://", "ws://").replace("https://", "wss://")
```

Token configurato dall'admin in HA (Profilo → Token a lungo termine →
Crea token), poi salvato in `admin_settings.ha_token`.

**Risoluzione adapter al runtime**: `cara/api/v1/smarthome.py:_resolve_adapter`
costruisce un nuovo `HomeAssistantAdapter` per ogni richiesta dai
settings correnti. Cache della singola istanza per process; invalidata
se il token-prefisso cambia (admin lo aggiorna).

### Capability mapping

L'adapter espone le entità HA traducendone i `domain` HA in `Capability`:

| HA domain | Capability tradotte |
|---|---|
| `light` | `ON_OFF, BRIGHTNESS, COLOR, COLOR_TEMP` |
| `switch` | `ON_OFF` |
| `cover` | `OPEN_CLOSE, POSITION, TILT` |
| `lock` | `LOCK_UNLOCK` |
| `media_player` | `PLAY_PAUSE, VOLUME, SOURCE` |
| `climate` | `TEMPERATURE, HVAC_MODE, FAN_MODE` |
| `scene` | `SCENE_ACTIVATE` |
| `script` | `SCRIPT_RUN` |
| `automation` | `AUTOMATION_TRIGGER` |
| `binary_sensor` | (read-only, no capability) |
| `sensor` | (read-only) |

### Errors

- 404 da HA → `get_state` ritorna None (entità rimossa)
- HTTP error → `call_service` ritorna `{ok: False, error: "..."}`
- Token sbagliato → 401 propagato

## 12.3 WebSocket events — `cara.smarthome.ws_client`

**File**: `cara/smarthome/ws_client.py`.

HA ha una WebSocket che pubblica `state_changed` events in tempo reale.
CARA si subscribe e li scrive in `events` come `kind=ha.state_changed`.

**Service**: `cara/services/smarthome_events.py:run_loop`. Avviato
automaticamente al boot del backend (sempre — se HA non c'è,
riconnette ogni 30s).

**Flow**:

```
1. WebSocket connect a wss://ha:8123/api/websocket
2. auth_required → manda token
3. auth_ok → subscribe_events
4. Per ogni evento "state_changed":
   - episodic.record_async(
       kind="ha.state_changed",
       ref_id=entity_id,
       payload={"old": old_state, "new": new_state, "attrs": ...},
     )
5. Disconnect → loop di reconnect con backoff esponenziale
```

Gli eventi alimentano:
- Reflective batch (cap 8.7) per pattern detection
- Rules proattive (cap 11) come `door_open_long`, `lights_on_nobody_home`
- Diagnostic (cap 21)

## 12.4 NLU — natural language → action

**File**: `cara/smarthome/nlu.py`.

Quando l'utente dice "accendi la luce del salotto", la NLU deve:
1. Capire l'intent (TURN_ON)
2. Trovare l'entità ("luce salotto" → `light.salotto`)
3. Estrarre il valore se serve (es. "metti il volume al 50%" → 50)

### Cascata 4 stadi

```
1. Intent regex   → matcha "accendi/spegni/apri/chiudi/imposta" → Action enum
2. Alias exact    → "luce salotto" matches DeviceAlias.alias esatto?
3. Substring      → entità il cui friendly_name contiene "luce" e "salotto"
4. Embedding      → cosine fra utterance e tutti i friendly_name
```

Si ferma al primo stadio che produce match unico. Se due alias
matchano, ambiguity → `needs_clarification=True` (chat layer chiede
"quale luce?").

### Action enum

```python
class Action(str, Enum):
    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"
    TOGGLE = "toggle"
    OPEN = "open"
    CLOSE = "close"
    LOCK = "lock"
    UNLOCK = "unlock"
    SET_VALUE = "set_value"   # "imposta a X"
    QUERY = "query"           # "qual è la temperatura?"
    SCENE_ACTIVATE = "scene_activate"
```

### Esempio di uso

```python
from cara.smarthome.nlu import SmartHomeNLU, aliases_from_entities

nlu = SmartHomeNLU(
    aliases=aliases_from_entities(entities),
    embedder=embedder,  # opzionale, per stadio 4
    ambiguity_threshold=0.05,
)

res = await nlu.resolve("accendi la luce del salotto")
# Resolution(matched_intent=True, action=TURN_ON,
#            target_phrase="luce del salotto",
#            candidates=[DeviceCandidate(entity_id="ha:light.salotto", score=1.0)],
#            needs_clarification=False, confidence=1.0)
```

### Presence disambiguation

Se due entità sono "luce" (cucina + salotto) e l'utente dice solo
"accendi la luce", la NLU usa la presence (chi è in casa) per
disambiguare:

```python
res = await nlu.resolve("accendi la luce", present_in_area="salotto")
# preferisce light.salotto perché "salotto" è l'area presente
```

Il chat layer passa il dato dal frigate-faces se disponibile.

### Accent-aware

`Caffè → caffe` per il match. Cosi "accendi la luce del caffè"
matches `light.caffe` (utenti pigri non mettono accenti).

## 12.5 Permessi — `cara.services.smarthome_permissions`

**File**: `cara/services/smarthome_permissions.py` + `cara/models/device_permission.py`.

Non tutti possono fare tutto. Default matrix per ruolo:

| Action / Role | parent | teen | child | elder | guest |
|---|---|---|---|---|---|
| `query` | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW |
| `control` (luci, switch) | ALLOW | ALLOW | DENY (no climate) | ALLOW | DENY |
| `lock_unlock` | ASK | DENY | DENY | DENY | DENY |
| `alarm` | ASK | DENY | DENY | DENY | DENY |
| `scene_activate` | ALLOW | ALLOW | DENY | ALLOW | DENY |

`ASK` = il backend ritorna `requires_confirmation=true` invece di
eseguire. Il frontend mostra un dialog "Sicuro?". L'utente conferma e
il backend riesegue con `confirmed=true`.

`DENY` = 403 secco.

### check_permission

```python
from cara.services.smarthome_permissions import check_permission, ACTION_CONTROL

decision = await check_permission(
    session, user_id=42, role="parent",
    entity_id="ha:lock.porta_ingresso",
    action=ACTION_LOCK,
)
# PermissionCheck(decision="ASK", matched_pattern="*:lock.*",
#                 matched_source="role_default", reason="parent ASK on locks")
```

### Rules per-utente (override)

L'admin può definire regole esplicite per singolo utente:

```sql
INSERT INTO device_permissions
(user_id, entity_pattern, action, decision, reason)
VALUES
(5, 'ha:light.cameretta_marco', 'control', 'allow', 'Marco gestisce la sua stanza');
```

Pattern glob (`*.cameretta_*`). Specificità: pattern con più segmenti
non-wildcard battono i broader.

> **🔒 Sicurezza** — DENY anywhere wins: se un user ha sia
> ALLOW (per role) che DENY esplicito, vince DENY. Implicit deny è
> il default — niente regole = niente controllo.

## 12.6 Device aliases — alias custom

L'utente può chiamare le entità HA con i nomi che vuole. La tabella
`device_aliases` mappa `alias` → `entity_id`:

```python
class DeviceAlias:
    entity_id: str          # "ha:light.salotto"
    alias: str             # "luce del divano"
    area: str | None       # "salotto"
    source_user_id: int | None  # chi l'ha creato (NULL = admin globale)
```

Esempio: `"luce del divano"` → `ha:light.salotto` solo per Antonio.

API admin:

```
GET    /api/v1/admin/device-aliases
POST   /api/v1/admin/device-aliases
DELETE /api/v1/admin/device-aliases/{id}
POST   /api/v1/admin/device-aliases/preview  → testa la NLU
```

`preview` accetta una utterance e ritorna la Resolution che la NLU
darebbe — utile per tuning.

`merged_aliases(user_id)` ritorna l'unione di:

1. Auto-generati da `friendly_name` HA (es. "Luce Salotto" → "luce salotto")
2. Admin globali (`source_user_id IS NULL`)
3. Per-user dell'utente corrente

In ordine di priorità inverso (più specifico vince).

## 12.7 Endpoints REST

**File**: `cara/api/v1/smarthome.py`.

| Endpoint | Method | Cosa fa |
|---|---|---|
| `/smarthome/entities` | GET | Lista entità con capability |
| `/smarthome/entities/{id}/state` | GET | Stato attuale (gated `ACTION_QUERY`) |
| `/smarthome/scenes` | GET | Scene definite in HA |
| `/smarthome/health` | GET | Stato adapter (sempre risponde) |
| `/smarthome/services` | POST | Chiama un service HA con permessi |
| `/smarthome/resolve` | POST | NLU dry-run (debug) |

### POST /smarthome/services

Body:

```json
{
  "domain": "light",
  "service": "turn_on",
  "entity_id": "ha:light.salotto",
  "params": {"brightness": 200},
  "confirmed": false
}
```

Flow:

1. `check_permission(user, entity, action)` → ALLOW/ASK/DENY
2. Se DENY → 403
3. Se ASK + `confirmed=false` → 200 con `{requires_confirmation: true}`
4. Se ALLOW (o ASK + confirmed=true) → adapter.call_service → 200

## 12.8 Chat tier — `try_smarthome`

**File**: `cara/api/v1/_chat_routing.py:try_smarthome`.

È la prima cosa che il chat router prova (Tier-0.35), prima ancora
delle skill.

**Flow**:

1. **Prefilter regex** veloce: l'utterance contiene un verbo control
   (`accendi/spegni/apri/chiudi/...`)? Se no → return None (skip
   smart home).
2. Lazy import dell'adapter HA.
3. `nlu.resolve(utterance)` → Resolution.
4. Se `needs_clarification` → return None (LLM rephrase).
5. `check_permission` → DENY → return None (LLM spiega).
6. Mappa Action → (HA domain, service).
7. `adapter.call_service(...)`.
8. Risposta canned: "Fatto, ho acceso luce salotto." → SSE shape.

Il prefiltro evita di costruire la NLU per il 99% dei messaggi
chat che non sono smart-home.

## 12.9 UI admin — `/admin/smart-home`

**File**: `frontend/src/routes/AdminSmartHomePage.tsx`.

Tab di gestione:

- **Entities**: lista entità HA, capability, area, alias
- **Scenes**: scene HA + pulsante trigger
- **NLU debug**: campo testo + risultato Resolution per test
- **Aliases**: CRUD device_aliases globali
- **Events tail**: ultimi 50 `ha.state_changed` (real-time SSE)

Endpoints già coperti in 12.7.

## 12.10 Estendere — adapter MQTT

Esempio: vuoi aggiungere supporto MQTT per device non-HA.

**1. Implementa Protocol**:

```python
# cara/smarthome/mqtt.py
import asyncio_mqtt as aiomqtt

class MQTTAdapter:
    provider = "mqtt"

    def __init__(self, broker: str, port: int = 1883, username=None, password=None):
        self._broker = broker
        # ...

    async def list_entities(self) -> list[Entity]:
        # Discovery via topics retained tipo "homeassistant/+/+/config"
        ...

    async def call_service(self, domain, service, entity_id, params):
        # Pubblica su topic "casa/<entity>/cmd" con payload
        ...

    # ...altri metodi del Protocol
```

**2. Registra** in `_resolve_adapter` di `cara/api/v1/smarthome.py`:

```python
async def _resolve_adapter(session) -> SmartHomeAdapter | None:
    settings = await admin_settings.get_all(session)
    if settings.get("mqtt_enabled"):
        return MQTTAdapter(broker=settings["mqtt_broker"], ...)
    if settings.get("smart_home_enabled"):
        return HomeAssistantAdapter(...)
    return None
```

**3. UI** — campo broker MQTT nel setup wizard step 6, oppure pannello
admin dedicato.

**4. Test smoke** che instanzia con un broker fake.

I service NLU + permissions funzionano automaticamente — sono
provider-agnostic.

## 12.11 Errori comuni

| Sintomo | Causa | Risoluzione |
|---|---|---|
| `health` ritorna `ok=false` | HA giù o token sbagliato | Verifica HA running + token valido in `admin_settings.ha_token` |
| Entità non trovate | HA non espone certi domain | Verifica HA Configuration → Integrations |
| NLU sempre `needs_clarification` | Embedder non disponibile | Avvia embedder service o spegni stadio 4 |
| Push proattività `lights_on_nobody_home` non fira | family adapter offline | Verifica frigate-faces → `who_is_home()` ritorna lista |

---

[← Cap 11 Proattività](11-proattivita.md) · [README](README.md) · [Cap 13 CDA →](13-cda.md)
