# Cap 22 — Test

> *Sintesi 30 secondi.* Tre suite. **Unit** (`tests/unit/`) gira in
> in-memory SQLite, ~10 secondi, 641+ test. **Smoke** (`tests/smoke/`)
> gira contro backend live via httpx, ~50 secondi, 160+ test. **E2E**
> Playwright (`frontend/e2e/`) richiede Chromium x86_64, gira da PC
> sviluppo. Totale 800+ verdi.

## 22.1 Tre livelli

| | Unit | Smoke | E2E |
|---|---|---|---|
| Cosa testa | Singola funzione/classe | Endpoint HTTP via curl analog | Flusso utente reale |
| Backend richiesto | NO (SQLite in-memory) | SÌ (httpx vs live) | SÌ |
| Frontend richiesto | NO | NO | SÌ (Chromium) |
| Velocità | ~10s | ~50s | minuti |
| Affidabilità | Alta (deterministico) | Alta (DB stabile) | Media (timing-sensitive) |
| Quando li lanci | Ogni save in IDE | Pre-commit | Pre-release |

## 22.2 Unit tests — `backend/tests/unit/`

**File principali**:
- `tests/unit/conftest.py` — fixture `db_session` (in-memory SQLite con
  compile JSONB→JSON, UUID→CHAR(36), BigInt→INTEGER per rendere i
  modelli Postgres-shaped girabili in-memory)
- `tests/unit/test_*.py` — uno per modulo

### Esegui

```bash
cd /opt/cara/backend
.venv/bin/python -m pytest tests/unit -q
# 641 passed, 4 skipped, 80 warnings in 11.05s

# Solo un file
.venv/bin/python -m pytest tests/unit/test_proactivity_rules.py -v

# Solo un test
.venv/bin/python -m pytest tests/unit/test_proactivity_rules.py::test_morning_greeting -v

# Con failure verboso
.venv/bin/python -m pytest tests/unit -v --tb=short
```

### Pattern fixture

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

@pytest.mark.asyncio
async def test_my_thing(db_session: AsyncSession):
    from cara.models.task import Task
    from cara.models.user import User

    # Arrange
    user = User(email="t@t", full_name="T", password_hash="x",
                is_admin=False, is_active=True, role="parent")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    task = Task(user_id=user.id, title="test")
    db_session.add(task)
    await db_session.commit()

    # Act
    from cara.services.tasks import list_tasks
    rows = await list_tasks(db_session, user_id=user.id)

    # Assert
    assert len(rows) == 1
    assert rows[0].title == "test"
```

### Convenzioni

- **Async** ovunque (`@pytest.mark.asyncio`)
- **Asserts atomici** — un test fa una cosa
- **AAA pattern** (Arrange / Act / Assert) — leggibile in ordine
- **No real I/O** — niente HTTP esterni, niente Redis reale (usa
  `FakeRedis`), niente file system (`tmp_path` se serve)
- **Mock pesanti**: spaCy, Tesseract, sentence-transformers vengono
  mockati lazy (non importati al top di file test)

### Coverage

```bash
.venv/bin/python -m pytest tests/unit \
  --cov=cara --cov-report=html
open htmlcov/index.html
```

Target attuale: ~70% sui moduli critici (cara.api, cara.services,
cara.skills, cara.workflows). Il restante (cara.ai con NPU bindings)
non è facilmente testabile in unit.

## 22.3 Smoke tests — `backend/tests/smoke/`

**Cosa**: black-box HTTP contro un backend running. Replicano
esattamente quello che fa il frontend.

**File principali**:
- `tests/conftest.py` — `http` (httpx anonimo), `auth_client` (utente
  fresh registrato), `admin_client` (admin Antonio)
- `tests/smoke/test_*.py` — uno per dominio

### Esegui

```bash
cd /opt/cara/backend
.venv/bin/python -m pytest tests/smoke -q
# 160 passed in 39.67s
```

Il backend deve essere up + healthy. Default URL:
`https://192.168.1.23:8455`. Override:

```bash
CARA_TEST_BASE_URL=https://other.host:8455 \
  .venv/bin/python -m pytest tests/smoke
```

### Pattern fixture

```python
@pytest.mark.asyncio
async def test_create_task(auth_client):
    r = await auth_client.post(
        "/api/v1/tasks",
        json={"title": "Test smoke task"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "Test smoke task"

    # Cleanup (best-effort)
    await auth_client.delete(f"/api/v1/tasks/{body['id']}")
```

### Fixture session-scoped

`test_user` (e quindi `auth_client`) è session-scoped: un test user
fresh viene creato per tutta la pytest session, NON per ogni test.
Cosi i test non si interferiscono ma sono efficienti.

`admin_client` legge le credenziali admin dal env (`CARA_TEST_ADMIN_EMAIL`,
`CARA_TEST_ADMIN_PASSWORD`) con default sui valori in CLAUDE.md
(`pedotoa@gmail.com` / `caracasa2026`).

### Idempotenza

Ogni smoke run lascia il DB in uno stato dove il prossimo run
funziona identicamente. Tre tecniche:

1. **Test user randomizzato**: ogni run ne crea uno nuovo
2. **Cleanup in finally**: le risorse create dal test vengono cancellate
3. **Resource scoping**: non si testano modifiche a risorse globali (admin
   settings) senza salvare lo stato e ripristinarlo

### Skip elegante

Se un test richiede una feature opt-in non configurata (es. Redis,
admin_client), `pytest.skip()` con messaggio:

```python
async def test_homeassistant_test_with_admin(admin_client):
    if admin_client is None:
        pytest.skip("admin_client fixture not available")
    # ...
```

## 22.4 E2E Playwright — `frontend/e2e/`

**File**: `frontend/e2e/playwright.config.ts` + `frontend/e2e/tests/*.spec.ts`.

Cosa testano:

- `01-smoke.spec.ts` — login error, manifest, sw.js, ca cert reachable
- `02-tasks.spec.ts` — create task → check → API delete cleanup
- `03-pwa-install.spec.ts` — Settings install button, version stamp
- `04-admin-skills.spec.ts` — `/admin/skills` mounts, tabs, primitive catalog
- `05-pair.spec.ts` — `/pair` shows 6-digit code

### Setup (sviluppatore PC)

```bash
cd frontend
npm install
npx playwright install chromium
```

> **⚠️ Attenzione** — Chromium è x86_64-only su Linux. Sul NanoPC
> ARM64 NON gira. Devi farlo da un PC sviluppo (Mac/Linux x86 o
> Windows) connesso alla stessa LAN o via WireGuard.

### Esegui

```bash
# Default contro backend live
PWBASE=https://192.168.1.23:8455 \
  npm run test:e2e

# Con UI (debug)
PWBASE=https://192.168.1.23:8455 \
  npm run test:e2e:headed

# Solo un file
npx playwright test e2e/tests/02-tasks.spec.ts
```

### Fixture personalizzate

`e2e/tests/fixtures.ts` espone:

- `loggedInPage` — Page già autenticata come admin
- `freshUserPage` — registra un nuovo user random + login

Ogni spec usa `import { test, expect } from './fixtures'` (NON da
`@playwright/test` direttamente — i fixture custom non funzionerebbero).

### Trace + screenshot

`playwright.config.ts` ha:
- `trace: 'retain-on-failure'`
- `screenshot: 'only-on-failure'`
- `video: 'retain-on-failure'`

Su test fallito → trace/screenshot/video salvati in `test-results/`.
Riproduzione bug 100x più rapida.

## 22.5 Test del LLM — strategie

Il LLM stesso è non-deterministic e lento. Tre strategie:

### Mock per unit

Per testare codice CHE USA il LLM senza chiamare il modello vero:

```python
class FakeLLMService:
    async def generate(self, prompt, **kwargs):
        # Generator finto
        yield TokenChunk(text="Risposta fake.", token_id=42)

# Inietta dipendenza in setup test
```

### Smoke con timeout largo

Per verificare che il LLM gira davvero, smoke test con timeout 30s:

```python
@pytest.mark.asyncio
async def test_chat_returns_some_text(auth_client):
    async with auth_client.stream(
        "POST", "/api/v1/chat",
        json={"message": "Ciao"},
        timeout=30.0,
    ) as r:
        assert r.status_code == 200
        chunks = []
        async for line in r.aiter_lines():
            if line.startswith("data:"):
                chunks.append(line)
        assert len(chunks) > 0
```

### Quality eval (futuro)

Test "il modello ha risposto bene a queste 50 domande?" — non
deterministic, da fare con eval framework manuale + LLM-judge.

## 22.6 Quando lanciare cosa

| Quando | Cosa lanci |
|---|---|
| Save file in IDE | tsc + unit test del file modificato |
| Pre-commit | Full unit suite |
| Pre-merge in main | Full unit + smoke |
| Pre-release | Tutti incluso E2E |
| Cron giornaliero (futuro) | Smoke contro produzione |

## 22.7 Scrivere test per nuove feature

Regola: **niente PR senza test**.

Per ogni nuovo:

| Tipo modifica | Test richiesto |
|---|---|
| Endpoint REST | Smoke (auth gate, happy path, validation) |
| Servizio business logic | Unit (happy path + edge case) |
| Modello ORM | Unit (CRUD round-trip) |
| Skill JSON | Smoke (run via /workflows o /chat) |
| Frontend component | E2E (mount + interaction) |
| Migration Alembic | Smoke su DB live |

### Template smoke endpoint

```python
import pytest
API = "/api/v1/foo"

@pytest.mark.asyncio
async def test_foo_requires_auth(http):
    r = await http.get(f"{API}")
    assert r.status_code in (401, 403)

@pytest.mark.asyncio
async def test_foo_validates_body(auth_client):
    r = await auth_client.post(f"{API}", json={"invalid": "x"})
    assert r.status_code == 422

@pytest.mark.asyncio
async def test_foo_happy_path(auth_client):
    r = await auth_client.post(f"{API}", json={"name": "test"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "test"
    # cleanup
    await auth_client.delete(f"{API}/{body['id']}")
```

### Template unit per servizio

```python
@pytest.mark.asyncio
async def test_service_function(db_session):
    from cara.services.foo import do_thing

    result = await do_thing(db_session, arg1="x")
    assert result.expected_field == ...

@pytest.mark.asyncio
async def test_service_handles_missing_arg(db_session):
    from cara.services.foo import do_thing

    with pytest.raises(ValueError, match="arg1 required"):
        await do_thing(db_session)
```

## 22.8 CI / GitHub Actions (futuro)

CARA non ha ancora CI automatico. Pianificato:

```yaml
# .github/workflows/test.yml (futuro)
name: tests
on: [push, pull_request]
jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - checkout
      - python 3.11
      - pip install -e backend[dev]
      - pytest backend/tests/unit -q
  smoke-against-staging:
    needs: unit
    runs-on: self-hosted  # un GitHub runner sulla LAN
    steps:
      - pytest backend/tests/smoke -q --base-url=https://staging.cara.lan
```

Effort ~1 EW. Bonus: se decidi di pubblicare CARA su GitHub, abilita
Actions e i contributor vedono CI verde/rosso prima di mergiare.

## 22.9 Errori comuni

| Sintomo | Causa | Risoluzione |
|---|---|---|
| `RuntimeError: Event loop is closed` | pytest-asyncio scope | Verifica `asyncio_default_fixture_loop_scope = "session"` in pyproject.toml |
| Smoke test 502 | Backend non running o riavvio | Aspetta 15s + ritenta |
| Unit test importa modulo pesante (cv2) | Import top-level | Sposta dentro la funzione che lo usa (lazy) |
| E2E timeout | Backend lento (NPU stressato) | Aumenta timeout in playwright.config: 60_000 |
| Test "passa" ma cambia stato globale | Cleanup mancante | Usa `try/finally` sempre |
| `migrations` non si applicano in unit | conftest non importa cara.models | Verifica `import cara.models` in `tests/unit/conftest.py` |

## 22.10 Code coverage minimo

Linee guida:

- Servizi critici (auth, settings, skill executor): ≥90%
- Endpoint REST: 100% degli endpoint hanno almeno auth-gate test
- Modelli ORM: ≥70% (CRUD basic + query principali)
- Helper utility: best-effort
- Codice "experimental" / Phase D: opt-in coverage

Misura periodicamente:

```bash
.venv/bin/python -m pytest tests/unit --cov=cara --cov-report=term-missing
```

Le righe non coperte appaiono in output. Considera se vale la pena
testarle (di solito sì per business logic, no per glue code).

---

[← Cap 21 Diagnostica e debug](21-diagnostica-debug.md) · [README](README.md) · [Cap 23 Deploy →](23-deploy.md)
