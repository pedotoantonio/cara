# Cap 25 — Estendere CARA (tutorial pratici)

> *Sintesi 30 secondi.* Tutorial passo-passo per le 5 estensioni più
> comuni: aggiungere un endpoint REST, un widget Wallet, una rule
> proattiva, una primitive skill, una migration Alembic. Ogni
> tutorial è copy-paste-able dalla command line e lascia il sistema
> funzionante.

I tutorial qui sono **versione completa** dei mini-tutorial
"Estendere" che trovi in fondo a ogni capitolo specifico.

## 25.1 Tutorial — endpoint REST nuovo

Voglio un endpoint `GET /api/v1/me/stats` che ritorni statistiche
dell'utente: # task aperte, # spese mese, # fact attivi.

### 1. Crea il file router

```python
# backend/cara/api/v1/me_stats.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from cara.api.deps import get_current_user, get_session
from cara.models.user import User
from cara.models.task import Task
from cara.models.budget import Expense
from cara.models.fact import Fact

router = APIRouter(prefix="/me", tags=["me"])


class MeStats(BaseModel):
    open_tasks: int
    expenses_month_count: int
    expenses_month_total_cents: int
    active_facts: int


@router.get("/stats", response_model=MeStats)
async def my_stats(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MeStats:
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Open tasks
    open_tasks = (await session.execute(
        select(func.count()).select_from(Task)
        .where(Task.user_id == user.id, Task.done.is_(False))
    )).scalar() or 0

    # Spese mese corrente
    exp_q = (await session.execute(
        select(
            func.count().label("n"),
            func.coalesce(func.sum(Expense.amount_cents), 0).label("total"),
        )
        .where(Expense.user_id == user.id, Expense.spent_on >= month_start.date())
    )).one()

    # Active facts
    active_facts = (await session.execute(
        select(func.count()).select_from(Fact)
        .where(Fact.user_id == user.id, Fact.active.is_(True))
    )).scalar() or 0

    return MeStats(
        open_tasks=int(open_tasks),
        expenses_month_count=int(exp_q.n),
        expenses_month_total_cents=int(exp_q.total),
        active_facts=int(active_facts),
    )
```

### 2. Registra il router

```python
# backend/cara/api/v1/__init__.py
from cara.api.v1 import (
    # ...esistenti
    me_stats,
)

router.include_router(me_stats.router)
```

### 3. Smoke test

```python
# backend/tests/smoke/test_me_stats.py
import pytest

@pytest.mark.asyncio
async def test_stats_requires_auth(http):
    r = await http.get("/api/v1/me/stats")
    assert r.status_code in (401, 403)

@pytest.mark.asyncio
async def test_stats_happy_path(auth_client):
    r = await auth_client.get("/api/v1/me/stats")
    assert r.status_code == 200
    body = r.json()
    assert "open_tasks" in body
    assert "expenses_month_count" in body
    assert isinstance(body["active_facts"], int)
```

### 4. Frontend client (opzionale)

```typescript
// frontend/src/api/me.ts
import { authFetch } from './auth';

export interface MeStats {
  open_tasks: number;
  expenses_month_count: number;
  expenses_month_total_cents: number;
  active_facts: number;
}

export async function getMyStats(): Promise<MeStats> {
  const r = await authFetch('/api/v1/me/stats');
  if (!r.ok) throw new Error(`stats: ${r.status}`);
  return r.json();
}
```

### 5. Deploy

```bash
docker cp backend/cara/api/v1/me_stats.py cara-backend:/app/cara/api/v1/me_stats.py
docker cp backend/cara/api/v1/__init__.py cara-backend:/app/cara/api/v1/__init__.py
docker restart cara-backend
sleep 8

# Test
TOK=$(curl -sk -X POST https://192.168.1.23:8455/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"pedotoa@gmail.com","password":"caracasa2026"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
curl -sk -H "Authorization: Bearer $TOK" \
  https://192.168.1.23:8455/api/v1/me/stats
```

## 25.2 Tutorial — widget Wallet nuovo

Vedi [Cap 10.10 — widget custom in 10 minuti](10-wallet-widgets.md#1010-tutorial--widget-custom-in-10-minuti).

Highlights:

1. Crea classe in `cara/widgets/catalog_extra.py`
2. Registra in `register_extra(registry, fetchers)`
3. Frontend: aggiungi caso `case 'next_birthday':` in
   `WidgetCard.tsx`
4. Restart backend + frontend
5. L'utente lo aggiunge al suo Wallet via PUT layout

## 25.3 Tutorial — rule proattiva nuova

Vedi [Cap 11.5 — aggiungere una rule custom](11-proattivita.md#115-tutorial--aggiungere-una-rule-custom).

Highlights:

1. Edita `cara/services/proactivity/rules.py`
2. `@rule(...)` decorator + funzione async
3. Aggiungi a `registered_rule_ids()` tuple
4. Test unit con `RuleContext` mockato
5. Deploy via `docker cp` + restart

## 25.4 Tutorial — primitive skill nuova

Vedi [Cap 9.2 — Aggiungere una primitive](09-skill-factory.md#aggiungere-una-primitive).

Highlights:

1. `@primitive(name=..., args_schema=..., returns_schema=...)` su
   funzione async
2. Aggiungi a `cara/skills/primitives.py` o nuovo file +
   importalo lì
3. Restart backend → registry aggiornato
4. Le skill JSON esistenti possono ora chiamarla
5. Test unit per l'happy path + edge case

## 25.5 Tutorial — migration Alembic nuova

Voglio aggiungere un campo `priority` (int, 0-3) alla tabella `tasks`.

### 1. Aggiorna il modello

```python
# backend/cara/models/task.py
from sqlalchemy import Integer

class Task(Base):
    # ...esistenti...
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
```

### 2. Genera migration

```bash
docker exec cara-backend alembic revision --autogenerate \
  -m "add task priority"
```

Output: `backend/alembic/versions/abc123_add_task_priority.py`.

### 3. Verifica + edita

Apri il file generato. Alembic genera:

```python
def upgrade() -> None:
    op.add_column(
        'tasks',
        sa.Column('priority', sa.Integer(), server_default='0', nullable=False),
    )

def downgrade() -> None:
    op.drop_column('tasks', 'priority')
```

OK così. Ma se vuoi un index, aggiungi:

```python
def upgrade() -> None:
    op.add_column('tasks', sa.Column('priority', sa.Integer(), ...))
    op.create_index('ix_tasks_priority', 'tasks', ['priority'])

def downgrade() -> None:
    op.drop_index('ix_tasks_priority')
    op.drop_column('tasks', 'priority')
```

### 4. Apply

```bash
# Backup PRIMA
docker exec cara-postgres pg_dump -U cara cara | gzip > \
  /opt/cara/backups/pre-priority-migration.sql.gz

# Apply
docker exec cara-backend alembic upgrade head

# Verifica
docker exec cara-backend alembic current
# abc123_add_task_priority (head)
```

### 5. Aggiorna schema Pydantic

```python
# backend/cara/schemas/task.py (se esiste)
class TaskOut(BaseModel):
    # ...
    priority: int = 0

class TaskCreate(BaseModel):
    # ...
    priority: int = Field(default=0, ge=0, le=3)
```

### 6. Aggiorna endpoint

```python
# backend/cara/api/v1/tasks.py
@router.post("", response_model=TaskOut, status_code=201)
async def create_task(body: TaskCreate, ...):
    task = Task(
        # ...
        priority=body.priority,
    )
    # ...
```

### 7. Smoke test

```python
@pytest.mark.asyncio
async def test_create_task_with_priority(auth_client):
    r = await auth_client.post("/api/v1/tasks", json={
        "title": "Test",
        "priority": 2,
    })
    assert r.status_code == 201
    assert r.json()["priority"] == 2
```

### 8. Frontend (opzionale)

Aggiungi `priority` a `Task` interface in `api/tasks.ts`. UI:
dropdown con opzioni 0-3 nel form di creazione task.

## 25.6 Tutorial — endpoint admin con audit

Voglio `POST /admin/family/import-vcf` che importa contatti da una
vCard.

### 1. Endpoint

```python
# backend/cara/api/v1/admin_import.py
from fastapi import APIRouter, Depends, Request, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import require_admin, get_session
from cara.models.user import User
from cara.services import audit as audit_svc

router = APIRouter(prefix="/admin/import", tags=["admin"])


class ImportResult(BaseModel):
    contacts_added: int
    skipped: int


@router.post("/vcf", response_model=ImportResult)
async def import_vcf(
    request: Request,
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ImportResult:
    content = (await file.read()).decode("utf-8", errors="replace")

    # Parse vCard (esempio semplificato)
    added, skipped = 0, 0
    for vcard_block in content.split("END:VCARD"):
        if "BEGIN:VCARD" not in vcard_block:
            continue
        # ...estrai FN, EMAIL, TEL, ADD, ecc.
        # ...persisti in DB tabella contacts (da creare)
        added += 1

    await audit_svc.record(
        session, actor=admin, action="admin.import.vcf",
        target_kind="contacts", target_id="batch",
        detail={"added": added, "skipped": skipped, "filename": file.filename},
        ip=request.client.host if request.client else None,
    )
    await session.commit()
    return ImportResult(contacts_added=added, skipped=skipped)
```

### 2. Registra + test smoke + deploy

(Stesso pattern di 25.1)

## 25.7 Tutorial — aggiungere un campo `admin_settings`

Voglio un flag `admin_settings.greeting_format` che accetta
"formal" o "informal".

### 1. Aggiungi a DEFAULTS

```python
# backend/cara/services/admin_settings.py
DEFAULTS: dict[str, Any] = {
    # ...esistenti
    "greeting_format": "informal",  # "formal" | "informal"
}
```

### 2. Usa nel codice

```python
# backend/cara/api/v1/_chat_system_prompt.py o dove rilevante
async def base_prompt(session) -> str:
    fmt = await admin_settings.get(session, "greeting_format")
    if fmt == "formal":
        return "Sei CARA. Dai del Lei alla famiglia. ..."
    else:
        return "Sei CARA. Dai del tu alla famiglia. ..."
```

### 3. UI admin

In `AdminPage.tsx`:

```tsx
// Aggiungi alla sezione AI behaviour
<div>
  <label className="block text-xs">Saluto</label>
  <select
    value={settings.greeting_format ?? 'informal'}
    onChange={(e) => patch({greeting_format: e.target.value}, "greeting_format")}
  >
    <option value="informal">Informale (tu)</option>
    <option value="formal">Formale (Lei)</option>
  </select>
</div>
```

Patch via `PATCH /admin/settings` ovviamente.

### 4. Test smoke

```python
@pytest.mark.asyncio
async def test_greeting_format_persists(admin_client):
    r = await admin_client.patch("/api/v1/admin/settings",
                                  json={"settings": {"greeting_format": "formal"}})
    assert r.status_code == 200

    r = await admin_client.get("/api/v1/admin/settings")
    assert r.json()["greeting_format"] == "formal"

    # Reset
    await admin_client.patch("/api/v1/admin/settings",
                              json={"settings": {"greeting_format": "informal"}})
```

## 25.8 Tutorial — SSE custom event

Voglio un evento `task_progress` durante esecuzione di workflow lunghi
("Step 3/7: download immagini...").

### Backend

```python
# Esempio dentro un endpoint che fa una task lunga
from fastapi.responses import StreamingResponse
from cara.api.v1._chat_sse import sse_frame

@router.post("/long-task")
async def long_task():
    async def stream():
        for i, step in enumerate(STEPS):
            yield sse_frame("task_progress", {
                "step": i+1, "total": len(STEPS), "label": step.name,
            })
            await step.run()
        yield sse_frame("done", {"status": "ok"})
    return StreamingResponse(stream(), media_type="text/event-stream")
```

### Frontend

```typescript
import { fetchEventSource } from '@microsoft/fetch-event-source';

await fetchEventSource('/api/v1/long-task', {
  headers: authHeaders(),
  onmessage(ev) {
    if (ev.event === 'task_progress') {
      const data = JSON.parse(ev.data);
      setProgress(`Step ${data.step}/${data.total}: ${data.label}`);
    }
  },
});
```

## 25.9 Tutorial — feature flag opt-in

Pattern per esporre una feature solo se l'admin la abilita.

### Backend

```python
# In un endpoint che dipende dalla feature
async def some_endpoint(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if not await admin_settings.get(session, "experimental_x_enabled"):
        raise HTTPException(503, "Feature disabilitata")
    # ...feature logic
```

### Frontend

```typescript
// Conditional render
const settings = useAdminSettings();
if (!settings.experimental_x_enabled) {
  return null;  // o <ComingSoon />
}
return <ExperimentalXFeature />;
```

### admin_settings DEFAULTS

```python
DEFAULTS = {
    # ...
    "experimental_x_enabled": False,  # opt-in
}
```

L'admin attiva via `/admin/settings`, le tab UI / endpoint REST si
attivano automaticamente.

## 25.10 Tutorial — webhook esterno

Voglio ricevere notifiche da Frigate quando rileva una persona, e
scriverle come evento `ha.state_changed`.

### 1. Endpoint

```python
# backend/cara/api/v1/webhooks.py
import secrets
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from cara.config import settings
from cara.learning import episodic

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class FrigateEvent(BaseModel):
    after: dict  # struttura Frigate
    type: str    # "new" | "update" | "end"


@router.post("/frigate")
async def frigate_webhook(body: FrigateEvent, request: Request):
    # Auth via secret nel header (no Bearer perché Frigate non lo manda)
    if request.headers.get("X-Webhook-Secret") != settings.frigate_webhook_secret:
        raise HTTPException(401, "Invalid webhook secret")

    after = body.after
    if after.get("label") != "person":
        return {"ok": True, "ignored": True}

    await episodic.record_async(
        kind="frigate.person_detected",
        ref_id=after.get("camera"),
        payload={
            "label": "person",
            "score": after.get("score"),
            "snapshot_url": f"https://192.168.1.23:8449/api/events/{after['id']}/snapshot.jpg",
        },
    )
    return {"ok": True}
```

### 2. Settings

```ini
# .env
FRIGATE_WEBHOOK_SECRET=<32 byte random>
```

### 3. Configura Frigate

Aggiungi al config Frigate:

```yaml
mqtt:
  enabled: false
webhooks:
  - url: https://192.168.1.23:8455/api/v1/webhooks/frigate
    headers:
      X-Webhook-Secret: <stesso secret>
```

### 4. Test

Provoca un evento Frigate (cammina davanti alla camera) e verifica:

```sql
SELECT * FROM events WHERE kind='frigate.person_detected' ORDER BY ts DESC LIMIT 5;
```

## 25.11 Convenzioni per nuove feature

Quando aggiungi qualcosa di non banale a CARA:

1. **Aggiungi flag** in `admin_settings.DEFAULTS` se è opt-in
2. **Test sempre** — almeno un smoke + un unit
3. **Audit log** — operazioni admin importanti
4. **Italian UI** se utente-visibile
5. **CHANGELOG.md** entry
6. **Docs** — aggiungi al cap relevant del manuale + aggiorna README index
7. **Migration** se cambia DB schema
8. **Frontend client** se aggiungi REST endpoint
9. **SSE/WS event** per cose live
10. **Feature flag iniziale OFF** — l'admin attiva quando è pronta

---

[← Cap 24 Manutenzione](24-manutenzione.md) · [README](README.md) · [Cap 26 Riferimento variabili .env →](26-env-vars.md)
