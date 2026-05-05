# CARA frontend E2E (Playwright)

Quick smoke + flow tests for the production frontend at
`https://192.168.1.23:8455`. They run against the **live** backend (not
a mock) so they double as a 30-second post-deploy sanity sweep.

## Setup (one time, on a developer machine — not the NanoPC)

The NanoPC-T6 is aarch64 and the Playwright Chromium build is
x86_64-only on Linux. Run from a Mac / Windows / x86 Linux with
network access to `192.168.1.23:8455` (LAN or WireGuard).

```bash
cd /opt/cara/frontend       # or wherever you cloned the repo
npm install                 # if you haven't already
npx playwright install chromium
```

## Running

```bash
# Default: against the live family server
PWBASE=https://192.168.1.23:8455 \
  npx playwright test --config e2e/playwright.config.ts

# Against a local dev backend instead
PWBASE=http://localhost:5173 \
  npx playwright test --config e2e/playwright.config.ts

# With a UI:
npx playwright test --config e2e/playwright.config.ts --headed --project=chromium-desktop
```

Override the admin credentials used by `loggedInPage` via:

```bash
PW_ADMIN_EMAIL=other-admin@example.com \
PW_ADMIN_PASSWORD=secret \
  npx playwright test --config e2e/playwright.config.ts
```

## What's covered

| Spec | Focus |
|------|-------|
| `01-smoke.spec.ts`        | Login error path, logged-in landing, manifest + sw + CA cert reachable |
| `02-tasks.spec.ts`        | Create task → check it → API delete cleanup (fresh user) |
| `03-pwa-install.spec.ts`  | Install button on Settings, version stamp, cert section, banner re-open |
| `04-admin-skills.spec.ts` | Skill Factory page mounts for admin, tabs render, generic primitives in catalog, non-admin blocked |
| `05-pair.spec.ts`         | Anonymous /pair page renders a 6-digit code |

## Adding new specs

Use the `test`/`expect` exports from `tests/fixtures.ts` (NOT directly
from `@playwright/test`) so you get the `loggedInPage` /
`freshUserPage` fixtures. Match user-facing strings (Italian) since the
UI is `lang="it"`. Trace + screenshot + video are retained on failure
under `test-results/`.
