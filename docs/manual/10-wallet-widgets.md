# Cap 10 — Wallet & widgets

> *Sintesi 30 secondi.* Il Wallet è la home page personalizzabile di
> CARA: una griglia di "widget" (mini-card che mostrano task, spesa,
> meteo, news brief, ecc.). Ogni utente ha il suo layout, salvato per
> surface (mobile/desktop/wall). 13 widget catalogati, 4 preset
> profili. L'engine è in `cara.widgets`, l'UI in `WalletPage.tsx`.

## 10.1 Cosa è un widget

Un widget è una card che mostra una piccola informazione o un'azione
rapida. Esempi:

- **today_summary** — quante task oggi, quanti appuntamenti
- **tasks_mine** — le tue prossime 3 task
- **shopping_quick** — prossimi 5 elementi da comprare
- **weather_now** — temperatura attuale + icona WMO
- **presence** — chi è in casa (da frigate-faces)
- **quick_actions** — pulsanti scorciatoia ("metti la radio", "chiudi tapparelle")
- **budget_month** — barra spesa categoria del mese
- **news_brief** — 3 titoli news del giorno
- **radio_now_playing** — cosa sta suonando

Nel sistema CARA un widget ha questo Protocol:

```python
from typing import Protocol

class Widget(Protocol):
    slug: str          # "tasks_mine"
    title: str         # "Le tue task"
    surfaces: tuple    # ("mobile", "desktop", "wall")
    sizes: tuple       # ("small", "medium", "large")
    visible_to_roles: tuple  # ("parent", "teen", "child", "elder", "guest")

    async def render(self, ctx: WidgetContext) -> WidgetData: ...
```

`WidgetData` è il payload JSON che il frontend renderizza:

```python
@dataclass
class WidgetData:
    title: str
    body: dict[str, Any]   # forma libera, il frontend sa interpretarla
    deep_link: str | None  # link cliccabile
    icon: str | None       # slug icona
```

## 10.2 Engine widget — `cara.widgets.base`

**File**: `cara/widgets/base.py`.

`WidgetRegistry` è un dict slug → Widget. Singleton process-wide via
`get_default_registry()`.

Pattern di registrazione:

```python
from cara.widgets.base import Widget, WidgetData, WidgetContext

class TodaySummaryWidget:
    slug = "today_summary"
    title = "Oggi in casa"
    surfaces = ("mobile", "desktop", "wall")
    sizes = ("small", "medium")
    visible_to_roles = ("parent", "teen", "child", "elder")

    async def render(self, ctx: WidgetContext) -> WidgetData:
        n_tasks = await ctx.fetchers.count_today_tasks(ctx.user_id)
        n_appts = await ctx.fetchers.count_today_appointments(ctx.user_id)
        return WidgetData(
            title=self.title,
            body={"tasks": n_tasks, "appointments": n_appts},
            deep_link="/tasks",
            icon="calendar",
        )

# Registrazione
from cara.widgets.base import get_default_registry
get_default_registry().register(TodaySummaryWidget())
```

### Isolation

Quando il frontend chiede di renderizzare 5 widget, il registry chiama
`render_many` che itera in parallelo. Errori in un widget **non**
rompono gli altri:

- `WidgetError` → mostra inline error nella card ("⚠ widget temporaneamente non disponibile")
- Eccezione generica → "errore interno", log come warning

Garanzia: **un widget rotto non rompe il Wallet**.

## 10.3 Catalogo widget

**File**: `cara/widgets/catalog.py` (7 core) + `catalog_extra.py` (6 extra).

13 widget totali:

| Slug | Cosa mostra | Surface | Size |
|---|---|---|---|
| `today_summary` | # task + # appuntamenti oggi | tutti | S/M |
| `tasks_mine` | Top 3 task aperte | tutti | M/L |
| `shopping_quick` | Prossimi 5 elementi spesa | tutti | M |
| `notes_recent` | Top 3 note recenti | tutti | M/L |
| `weather_now` | Temp + icona WMO | tutti | S |
| `presence` | Chi è in casa | tutti | S/M |
| `quick_actions` | Bottoni shortcut configurabili | tutti | S/M/L |
| `budget_month` | % spesa categoria mese | tutti | M |
| `kids_homework` | Promemoria compiti (per child) | tutti | M |
| `routine_next` | Prossima routine smart-home | tutti | S/M |
| `cara_quote` | Frase del giorno random | tutti | S |
| `news_brief` | 3 titoli giornata | desktop, wall | M/L |
| `radio_now_playing` | Stazione corrente + brano | tutti | S |

### Surface caps

Ogni surface ha un limite di widget visibili contemporaneamente:

```python
SURFACE_CAPS = {
    "watch": 2,    # piccolo schermo
    "mobile": 4,
    "desktop": 6,
    "wall": 8,
    "tv": 4,
}
```

`render_many` rispetta il cap del surface chiamante.

### Aggiungere un widget

**1. Crea la classe**:

```python
# cara/widgets/catalog_extra.py o nuovo file
class MotivationalQuoteWidget:
    slug = "motivational_quote"
    title = "Frase motivazionale"
    surfaces = ("mobile", "wall")
    sizes = ("S",)
    visible_to_roles = ("parent", "teen")

    async def render(self, ctx):
        from random import choice
        quotes = [
            "Una pianta non chiede permesso per crescere.",
            "L'errore di oggi è la base di domani.",
        ]
        return WidgetData(
            title=self.title,
            body={"text": choice(quotes)},
            deep_link=None, icon="sparkle",
        )
```

**2. Registrala**:

```python
# cara/widgets/catalog_extra.py
def register_extra(registry, fetchers):
    # ... esistenti ...
    registry.register(MotivationalQuoteWidget())
```

**3. Render lato frontend**:

Aggiungi al `WidgetCard.tsx` un caso per il nuovo slug:

```tsx
// frontend/src/components/widgets/WidgetCard.tsx
case 'motivational_quote':
  return (
    <Card>
      <p className="italic text-fg">{data.body.text}</p>
    </Card>
  );
```

**4. Riavvia**: il widget apparirà nel catalogo `/widgets`.

## 10.4 Layout per surface — `wallet_layouts`

Ogni utente può scegliere quali widget vedere e in quale ordine, per
ogni surface. Il layout è persistito in `wallet_layouts` come JSONB.

```python
class WalletLayout(Base):
    user_id: int
    surface: str       # "mobile"|"desktop"|"wall"|"watch"|"tv"
    layout: dict      # {"slots": ["today_summary", "tasks_mine", "weather_now", ...]}
    updated_at: datetime
```

API:

```
GET    /api/v1/wallet/layout?surface=mobile  → layout corrente
PUT    /api/v1/wallet/layout                  → sovrascrivi
DELETE /api/v1/wallet/layout?surface=mobile  → reset al default ruolo
GET    /api/v1/wallet/presets                  → lista preset disponibili
POST   /api/v1/wallet/preset/{slug}            → applica preset al user corrente
```

## 10.5 Preset profili

4 preset di layout pre-confezionati per ogni ruolo famiglia:

### `parent`
```
mobile:  [today_summary, tasks_mine, shopping_quick, weather_now]
desktop: [today_summary, tasks_mine, shopping_quick, news_brief, weather_now, budget_month]
```

Ottimizzato per gestione casa: task + spesa + meteo + budget +
news.

### `teen`
```
mobile:  [tasks_mine, weather_now, cara_quote, radio_now_playing]
desktop: [tasks_mine, kids_homework, notes_recent, weather_now, radio_now_playing, cara_quote]
```

Ottimizzato per studio + intrattenimento. Niente budget (non li
riguarda), niente shopping (lo gestiscono i genitori).

### `child`
```
mobile:  [kids_homework, weather_now, cara_quote]
desktop: [kids_homework, today_summary, weather_now, cara_quote, presence]
```

Semplificato: compiti, meteo, presenza famiglia, quote.

### `elder`
```
mobile:  [today_summary, weather_now, presence, quick_actions]
desktop: [today_summary, tasks_mine, weather_now, presence, quick_actions, news_brief]
```

Nessun budget, presenza famiglia in evidenza, quick_actions
configurate per chiamate / luci / televisione.

I preset vivono in `cara/services/wallet_layouts.py:PRESETS`.

## 10.6 Frontend — `WalletPage`

**File**: `frontend/src/routes/WalletPage.tsx`.

Flow al mount:

1. Detect surface dal `window.innerWidth` + user agent (mobile vs desktop)
2. `GET /wallet/layout?surface=<detected>` → ottieni la lista slug
3. Se 404, applica il preset del ruolo utente (`POST /wallet/preset/<role>`)
4. `GET /widgets/render?ids=...&surface=<>&size=medium` → ottieni payloads
5. Renderizza ogni payload con `WidgetCard.tsx`

**WidgetCard** è un dispatcher per slug: switch sul `slug` ritornato e
usa il layout JSX appropriato per il body.

## 10.7 Quick actions — widget configurabile

`quick_actions` è speciale: l'utente può configurare quali pulsanti
mostrare.

Schema action:

```typescript
interface QuickAction {
  label: string;          // "Metti la radio"
  icon?: string;          // "radio"
  tool: string;           // "play_radio"
  args: Record<string, unknown>;
}
```

Configurazione di default per ruolo (in `quick_actions` del registry):

```python
DEFAULTS = {
    "parent": [
        {"label": "Sveglia famiglia", "tool": "morning_routine", "args": {}},
        {"label": "Tutti via", "tool": "scene_activate", "args": {"scene": "uscita_casa"}},
        {"label": "Buona notte", "tool": "scene_activate", "args": {"scene": "buona_notte"}},
    ],
    "elder": [
        {"label": "Chiama Antonio", "tool": "call", "args": {"contact": "antonio"}},
        {"label": "TV su", "tool": "media_on", "args": {"target": "salotto"}},
    ],
}
```

L'admin può sovrascrivere via UI futura.

Surface caps applicano: watch=2 actions, mobile=4, desktop/wall=6.

## 10.8 Tutorial — preset custom per la famiglia

Vuoi un preset "ospite" che mostra solo meteo + chi è in casa + frase
del giorno?

**1. Aggiungilo a PRESETS**:

```python
# cara/services/wallet_layouts.py
PRESETS["guest"] = {
    "mobile": ["weather_now", "presence", "cara_quote"],
    "desktop": ["weather_now", "presence", "cara_quote", "today_summary"],
    "wall": ["weather_now", "presence", "cara_quote", "today_summary", "radio_now_playing"],
    "watch": ["weather_now", "presence"],
    "tv": ["weather_now", "presence", "cara_quote", "today_summary"],
}
```

**2. Aggiungi visibilità widget**:

Verifica che ogni widget elencato abbia `"guest"` in
`visible_to_roles`. Se manca, l'utente guest non lo vedrà
(filtro `available_for(role)`).

**3. Esegui in DB**:

```sql
-- per ogni utente con role='guest', cancella la layout corrente:
DELETE FROM wallet_layouts WHERE user_id IN (SELECT id FROM users WHERE role='guest');
-- alla prossima visita, applicheranno il nuovo PRESET["guest"]
```

Oppure più chirurgico, l'admin può forzare per il singolo utente:

```bash
curl -sk -X POST -H "Authorization: Bearer $ADMIN_TOK" \
  https://192.168.1.23:8455/api/v1/admin/wallet/users/<user_id>/preset/guest
```

(endpoint da scrivere — al momento esiste solo self-service per l'utente
corrente).

## 10.9 Errori comuni

| Sintomo | Causa | Risoluzione |
|---|---|---|
| Widget mostra "errore interno" | Eccezione nel `render()` | `docker logs cara-backend \| grep widget` |
| Widget non appare nel catalogo `/widgets` | Slug non registrato | Verifica `register_all()` chiamato al boot |
| Layout non persistito | PUT senza payload corretto | Verifica formato `{slots: [...]}` |
| Surface cap troppo basso | Default conservativo | Cambia in `surface_caps` |

## 10.10 Tutorial — widget custom in 10 minuti

Voglio un widget "compleanno-prossimo" che mostra il prossimo
compleanno in famiglia.

**1. Backend** — `cara/widgets/catalog_extra.py`:

```python
class NextBirthdayWidget:
    slug = "next_birthday"
    title = "Prossimo compleanno"
    surfaces = ("mobile", "desktop", "wall")
    sizes = ("S", "M")
    visible_to_roles = ("parent", "teen", "child", "elder")

    async def render(self, ctx):
        from datetime import date, timedelta
        from sqlalchemy import select
        from cara.models.user import User

        users = (
            await ctx.session.execute(
                select(User).where(User.is_active.is_(True))
                                  .where(User.birth_date.is_not(None))
            )
        ).scalars().all()

        today = date.today()
        candidates = []
        for u in users:
            bd = u.birth_date.replace(year=today.year)
            if bd < today:
                bd = bd.replace(year=today.year + 1)
            candidates.append((bd - today, bd, u))

        if not candidates:
            return WidgetData(title=self.title,
                              body={"empty": True}, deep_link=None, icon="cake")

        candidates.sort()
        days_left, bd, u = candidates[0]
        first_name = (u.full_name or u.email).split()[0]
        return WidgetData(
            title=self.title,
            body={
                "name": first_name,
                "days_left": days_left.days,
                "date": bd.isoformat(),
            },
            deep_link=None, icon="cake",
        )
```

**2. Registra**: in `register_all` aggiungi `registry.register(NextBirthdayWidget())`.

**3. Frontend** — `frontend/src/components/widgets/WidgetCard.tsx`:

```tsx
case 'next_birthday':
  if (data.body.empty) return <Card><p className="text-sm">Nessun compleanno noto</p></Card>;
  return (
    <Card>
      <p className="text-xs text-fg-muted">{data.title}</p>
      <p className="text-2xl font-bold">{data.body.name}</p>
      <p className="text-sm">
        fra {data.body.days_left} {data.body.days_left === 1 ? 'giorno' : 'giorni'}
      </p>
    </Card>
  );
```

**4. Restart + reload**:

```bash
docker restart cara-backend
# Forza refresh frontend (versione bumpata?)
```

L'utente può ora aggiungerlo al suo Wallet via PUT layout.

---

[← Cap 9 Skill Factory](09-skill-factory.md) · [README](README.md) · [Cap 11 Proattività →](11-proattivita.md)
