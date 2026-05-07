# Cap 11 — Proattività

> *Sintesi 30 secondi.* CARA non risponde solo: propone. Ogni 10 minuti
> uno scheduler valuta 10 regole concrete (saluto mattutino, allerta
> pioggia, porte aperte, compleanni, ecc.) e per ogni hit manda un push
> all'utente. Le regole vivono in `cara.services.proactivity.rules`,
> l'engine è in `engine.py`. Tutto è disabilitato di default.

## 11.1 Engine — `cara.services.proactivity.engine`

**File**: `cara/services/proactivity/engine.py`.

L'engine è una libreria pura: mantiene un registry di rule, e quando
chiamato (`tick()`) le valuta tutte e ritorna le `Suggestion`
prodotte.

**Concetti chiave**:

| Concept | Descrizione |
|---|---|
| `Rule` | Funzione async che prende un `RuleContext` e ritorna `Suggestion \| list[Suggestion] \| None` |
| `RuleContext` | Wide context: `now`, `db_session`, `smarthome` adapter, `weather`, `family` |
| `Suggestion` | Output: `rule_id`, `text`, `priority`, `target_user_id?`, `action?`, `expires_at?` |
| `Priority` | LOW=10, MEDIUM=30, HIGH=60, URGENT=90 |
| **Cooldown** | Default 24h per rule. Una rule che ha già firato di recente non rifirea. |
| **Silent hours** | Default 22:00-07:00. Mute tutto eccetto URGENT. Wrap-around overnight. |

### Registrazione di una rule

Due forme:

```python
# Decorator (top-level)
from cara.services.proactivity.engine import rule, RuleContext, Priority, Suggestion

@rule(
    "morning_greeting",
    cooldown_hours=20.0,
    description="Saluto mattutino fra le 7 e le 10",
)
async def morning_greeting(ctx: RuleContext) -> Suggestion | None:
    if ctx.now.hour < 7 or ctx.now.hour >= 10:
        return None
    return Suggestion(
        rule_id="morning_greeting",
        text="Buongiorno! Pronto per iniziare?",
        priority=Priority.LOW,
    )
```

```python
# Imperative (test, runtime register)
from cara.services.proactivity.engine import register_rule

register_rule(
    "my_rule", my_func,
    cooldown_hours=2.0,
    description="...",
)
```

### Tick — valutare tutte le rules

```python
from cara.services.proactivity.engine import ProactivityEngine

engine = ProactivityEngine()
ctx = RuleContext(
    now=datetime.now(ROME_TZ),
    db_session=session,
    smarthome=ha_adapter,
    weather=weather_service,
    family=family_service,
)
suggestions = await engine.evaluate(ctx)
# Lista di Suggestion da consegnare via push, dashboard, ecc.
```

**Isolation**: una rule che lancia eccezione **non** rompe le altre.
L'engine la cattura, logga `proactivity.rule.exception`, e procede.

**Cooldown**: l'engine tiene `last_fired_at` per rule_id. Le rule
suggestion sotto cooldown vengono droppate.

**Silent hours**: configurabili via `engine.silent_hours = (start_hour,
end_hour)`. Wrap-around supportato (es. 22→07).

## 11.2 Le 10 regole concrete

**File**: `cara/services/proactivity/rules.py`.

| Rule | Quando fira | Cooldown | Priority |
|---|---|---|---|
| `morning_greeting` | 7-10am, una volta | 20h | LOW/MEDIUM |
| `undone_tasks_evening` | 19-22, ricorda task aperte | 18h | MEDIUM |
| `rain_alert` | Pioggia in 3h, prendi ombrello | 4h | MEDIUM |
| `door_open_long` | Porta aperta da >20 min | 1h | HIGH |
| `bedtime_routine` | 22:30-23:30, "buona notte?" | 20h | MEDIUM |
| `birthday_today` | 6am+ se è il compleanno di un membro | 23h | HIGH |
| `shopping_review_saturday` | Sab 9-12 con lista non vuota | 144h (1/sett) | MEDIUM |
| `task_overdue_24h` | Task in ritardo da ≥24h | 24h | MEDIUM |
| `budget_drift_warning` | Categoria spesa >80% target | 72h | LOW |
| `lights_on_nobody_home` | Casa vuota + luci accese (8-22) | 2h | HIGH |

### Esempio: morning_greeting

```python
@rule(
    "morning_greeting",
    cooldown_hours=20.0,
    description=(
        "Una volta al giorno fra le 7 e le 10 saluta e riassume "
        "task / appuntamenti di oggi."
    ),
)
async def morning_greeting(ctx: RuleContext) -> Suggestion | None:
    h = ctx.now.hour
    if h < 7 or h >= 10:
        return None  # fuori finestra

    if ctx.db_session is None:
        return Suggestion(
            rule_id="morning_greeting",
            text="Buongiorno! Pronto per iniziare la giornata?",
            priority=Priority.LOW,
        )

    # Conta le task di oggi
    rows = await ctx.db_session.execute(...)
    today_count = sum(1 for t in rows if t.due_date.date() == today)

    if today_count == 0:
        text = "Buongiorno! Oggi hai la giornata libera, niente di urgente."
    elif today_count == 1:
        text = "Buongiorno! Hai 1 cosa in programma oggi."
    else:
        text = f"Buongiorno! Hai {today_count} cose in programma oggi."

    return Suggestion(
        rule_id="morning_greeting",
        text=text,
        priority=Priority.MEDIUM if today_count > 0 else Priority.LOW,
        action={"deep_link": "/tasks"},
        expires_at=ctx.now.replace(hour=23, minute=59),
    )
```

### Difensività delle rules

Ogni rule deve essere **defensiva**:
- Adapter mancante → `return None` (non eccezione)
- Query fallisce → `return None`
- Risultato vuoto → `return None` (non Suggestion vuota)

**Esempio rain_alert** che gestisce 4 modi di fallire:

```python
async def rain_alert(ctx: RuleContext) -> Suggestion | None:
    if ctx.weather is None:
        return None  # adapter assente
    fn = getattr(ctx.weather, "forecast_next_hours", None)
    if fn is None:
        return None  # API diversa
    try:
        forecast = await fn(hours=3)
    except Exception:
        return None  # network fail
    if not forecast:
        return None  # forecast empty
    # ... business logic
```

## 11.3 Scheduler — `proactivity_scheduler.py`

**File**: `cara/services/proactivity_scheduler.py`.

Loop asyncio che gira ogni `PROACTIVITY_SCHEDULER_INTERVAL_SECONDS`
(default 600s = 10 minuti):

```python
async def run_loop(sessionmaker):
    interval = settings.proactivity_scheduler_interval_seconds
    log.info("proactivity_scheduler.start", interval_seconds=interval)
    while True:
        try:
            await _tick(sessionmaker)
        except Exception as exc:
            log.warning("proactivity_scheduler.tick_failed", error=str(exc))
        await asyncio.sleep(interval)
```

`_tick`:

1. Importa `cara.services.proactivity.rules` (registra le 10 rules)
2. Costruisce `RuleContext` con `now`, `db_session`, adapter
3. `engine.evaluate(ctx)` → lista Suggestion
4. Per ogni Suggestion:
   - Se `target_user_id` è None → fan-out a tutti i membri famiglia
   - Push via VAPID a ognuno
   - Scrivi episodic event `proactivity.suggestion`

### Avvio condizionale

Il scheduler **NON** parte se push non è configurato:

```python
# cara/main.py lifespan
if push_is_configured():
    proactivity_task = asyncio.create_task(
        proactivity_scheduler_loop(get_sessionmaker()),
        name="proactivity_scheduler",
    )
else:
    log.info("cara.proactivity_scheduler_skipped", reason="vapid_not_configured")
```

Cosi senza VAPID il scheduler resta dormiente — niente push, niente
fan-out a vuoto.

## 11.4 UI admin — `/admin/proactivity`

**File**: `frontend/src/routes/AdminProactivityPage.tsx`.

Pagina admin con:

- **Lista rules**: tutte quelle registrate, con cooldown, last_fired,
  status (on/off)
- **Toggle on/off** per rule (set `enabled=false` nel registry runtime
  — non persiste; per persistere edita il codice)
- **Pulsante "Esegui ora"**: forza `engine.evaluate()` immediato e
  mostra cosa avrebbe prodotto
- **Suggestion recenti**: ultime 50, con per-utente delivery status

Endpoints:

```
GET  /api/v1/admin/proactivity/rules         — lista
POST /api/v1/admin/proactivity/evaluate      — tick on-demand
GET  /api/v1/admin/proactivity/suggestions    — lista
PATCH /api/v1/admin/proactivity/rules/{id}   — toggle enabled
```

## 11.5 Tutorial — aggiungere una rule custom

Esempio: "frigo aperto da troppo": fira HIGH se la porta del frigo è
aperta da >5 minuti.

**1. Edita `cara/services/proactivity/rules.py`**:

```python
@rule(
    "fridge_open_too_long",
    cooldown_hours=0.5,    # 30 min cooldown — fira spesso
    description="Avvisa se il frigo è aperto da più di 5 minuti",
)
async def fridge_open_too_long(ctx: RuleContext) -> Suggestion | None:
    if ctx.db_session is None:
        return None

    from datetime import timedelta
    from sqlalchemy import desc, select
    from cara.models.event import Event

    cutoff = ctx.now - timedelta(minutes=10)
    rows = (
        await ctx.db_session.execute(
            select(Event)
            .where(Event.kind == "ha.state_changed")
            .where(Event.ts >= cutoff)
            .order_by(desc(Event.ts))
        )
    ).scalars().all()

    # Filtra entity_id che contengono "frigo" o "fridge"
    open_since = None
    for r in reversed(rows):
        eid = r.ref_id or ""
        if "frigo" not in eid.lower() and "fridge" not in eid.lower():
            continue
        new_st = (r.payload or {}).get("new")
        if new_st in ("on", "open"):
            open_since = open_since or r.ts
        else:
            open_since = None  # chiuso → reset

    if open_since is None:
        return None
    if (ctx.now - open_since) < timedelta(minutes=5):
        return None

    return Suggestion(
        rule_id="fridge_open_too_long",
        text="Il frigo è aperto da più di 5 minuti. Chiuderlo?",
        priority=Priority.HIGH,
        action={"deep_link": "/casa"},
    )
```

**2. Aggiungi a `registered_rule_ids()`**:

```python
def registered_rule_ids() -> tuple[str, ...]:
    return (
        "morning_greeting",
        # ... esistenti ...
        "fridge_open_too_long",   # nuova
    )
```

**3. Test unit**:

```python
# tests/unit/test_proactivity_rules.py
@pytest.mark.asyncio
async def test_fridge_silent_when_no_session() -> None:
    ctx = RuleContext(now=_at(2026,5,7,12,0), db_session=None)
    assert await fridge_open_too_long(ctx) is None

@pytest.mark.asyncio
async def test_fridge_fires_when_open_long(db_session) -> None:
    from cara.models.event import Event
    db_session.add(Event(
        kind="ha.state_changed",
        ts=_at(2026,5,7,12,0) - timedelta(minutes=10),
        ref_id="binary_sensor.frigo_door",
        payload={"new": "on"},
    ))
    await db_session.commit()
    ctx = RuleContext(now=_at(2026,5,7,12,0), db_session=db_session)
    s = await fridge_open_too_long(ctx)
    assert s is not None
    assert "frigo" in s.text.lower()
```

**4. Restart**:

```bash
docker cp backend/cara/services/proactivity/rules.py cara-backend:/app/cara/services/proactivity/rules.py
docker restart cara-backend
sleep 8
docker logs --tail 5 cara-backend | grep proactivity.rules.loaded
# Verifica che ora siano 11 rules invece di 10
```

## 11.6 Configurazione globale

Tre flag controllano la proattività:

```python
admin_settings.proactive_suggestions_enabled  # master switch — default OFF
admin_settings.habit_learning_enabled          # alimenta le rule da habit detector
admin_settings.push_notifications_enabled      # gate per VAPID push
```

L'utente normale può anche disabilitare per il proprio account
(future feature) — al momento le rule fan-out a tutti i parent della
famiglia.

## 11.7 Privacy — silent hours per ruolo

Le silent hours globali (22:00-07:00) tagliano LOW e MEDIUM.
URGENT passa sempre.

Per rules legate a child / teen, `target_user_id` è settato
specificamente. Il push scheduler ha matrix per ruolo che decide:

- **child**: niente push dopo 21:00 (anche URGENT)
- **teen**: niente push dopo 22:00 (eccetto URGENT)
- **parent/elder**: rispettano le silent hours globali

> **🔒 Sicurezza** — non triggerare mai una notifica "ad alto volume"
> verso un device child senza esplicita configurazione parent. La
> matrix sopra è il default conservativo.

## 11.8 Errori comuni

| Sintomo | Causa | Risoluzione |
|---|---|---|
| Rule mai firata | Cooldown bloccato | Forza tick via `/admin/proactivity/evaluate` |
| Eccezione per rule | Adapter non disponibile | Aggiungi `if ctx.X is None: return None` |
| Push non arriva ma rule fira | VAPID non configurato | Genera chiavi via `/setup/vapid/generate` |
| Rule fira sempre (ignora cooldown) | Bug: `last_fired_at` non si aggiorna | Verifica che engine sia singleton, non ricreato per tick |
| Silent hours non rispettate | Priority troppo alta (URGENT bypassa) | Verifica priority della Suggestion |

---

[← Cap 10 Wallet & widgets](10-wallet-widgets.md) · [README](README.md) · [Cap 12 Smart home →](12-smart-home.md)
