# CARA test suite

Black-box smoke tests against a **running** CARA backend. They protect refactors
from breaking the API contract.

## Run

```bash
# against the live container (default)
make test-smoke

# against a custom backend
CARA_TEST_BASE_URL=http://localhost:8000 pytest backend/tests/smoke -v
```

## What's covered (Step 0.1)

| Module | What it asserts |
|--------|-----------------|
| `test_health.py` | `/health` and `/api/v1/chat/health` reachable, NPU loaded |
| `test_auth.py` | register → login → refresh → /me round-trip |
| `test_tasks.py` | task CRUD: create, list, patch (mark done), delete |
| `test_shopping.py` | shopping item CRUD + clear-bought |
| `test_conversations.py` | conversation create, list, fetch, delete |

## Design notes

- **HTTP black-box, no in-process import**: tests don't import `cara.*`. They
  hit the public API exactly like the frontend would. This means a refactor
  of internal modules can't accidentally pass tests.
- **Per-run unique user**: each pytest invocation creates a fresh
  `cara-test-<rand>@example.com` user. No cleanup needed — old test users are
  harmless and can be purged later with a maintenance job.
- **`-k smoke`-tag friendly**: every test is fast (<2s); `make test-smoke`
  finishes in under 10s on the NanoPC.

## What's NOT covered yet

- LLM streaming (`POST /api/v1/chat`) — needs more careful timing handling, see Step 0.4
- File ingestion + ChromaDB — Step 3.1+
- WebSocket family channel — Step 6.2
- Admin endpoints — Step 4.x
