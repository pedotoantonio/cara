#!/usr/bin/env bash
#
# Cattura tutti gli screenshot del manuale del programmatore.
#
# Da eseguire da un PC sviluppo con:
#   - Node.js 20+ + npm (per Playwright)
#   - Connessione di rete a 192.168.1.23 (LAN o WireGuard)
#   - CA mkcert installata come root trusted (vedi cap 2.9)
#
# Output in docs/manual/img/raw/  (poi pngquant li ottimizza in docs/manual/img/)
#
# Uso:
#   cd /opt/cara
#   bash docs/manual/scripts/take-screenshots.sh
#
# Override credenziali:
#   PW_ADMIN_EMAIL=other@example.com \
#   PW_ADMIN_PASSWORD=secret \
#   PWBASE=https://192.168.1.23:8455 \
#     bash docs/manual/scripts/take-screenshots.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
RAW_DIR="$ROOT/docs/manual/img/raw"
OUT_DIR="$ROOT/docs/manual/img"

PWBASE="${PWBASE:-https://192.168.1.23:8455}"
PW_ADMIN_EMAIL="${PW_ADMIN_EMAIL:-pedotoa@gmail.com}"
PW_ADMIN_PASSWORD="${PW_ADMIN_PASSWORD:-caracasa2026}"

mkdir -p "$RAW_DIR" "$OUT_DIR"

# Genera lo script Playwright temporaneo
PW_SCRIPT="$(mktemp -t cara-screenshots-XXXX.mjs)"
trap "rm -f $PW_SCRIPT" EXIT

cat > "$PW_SCRIPT" <<'JS'
import { chromium } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const BASE = process.env.PWBASE;
const EMAIL = process.env.PW_ADMIN_EMAIL;
const PASSWORD = process.env.PW_ADMIN_PASSWORD;
const RAW_DIR = process.env.RAW_DIR;

async function login(page) {
  await page.goto(`${BASE}/`);
  await page.getByLabel(/email/i).first().fill(EMAIL);
  await page.getByLabel(/password/i).first().fill(PASSWORD);
  await page.getByRole('button', { name: /accedi/i }).click();
  // Aspetta il mount del shell
  await page.waitForSelector('nav', { timeout: 10000 });
}

async function snap(page, slug) {
  const out = path.join(RAW_DIR, `${slug}.png`);
  await page.screenshot({ path: out, fullPage: false });
  console.log(`✓ ${slug}.png`);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    locale: 'it-IT',
    timezoneId: 'Europe/Rome',
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();

  // 1. Login screen (anon)
  await page.goto(`${BASE}/`);
  await page.waitForLoadState('networkidle');
  await snap(page, '00-login');

  // 2. Setup wizard reset → 8 screenshot
  await login(page);
  // Reset wizard
  const resetReq = await page.evaluate(async (base) => {
    const tok = localStorage.getItem('cara.access_token');
    const r = await fetch(`${base}/api/v1/setup/reset`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${tok}` },
    });
    return r.status;
  }, BASE);
  console.log(`reset setup: HTTP ${resetReq}`);

  await page.goto(`${BASE}/admin/setup`);
  await page.waitForTimeout(1000);
  await snap(page, '18-2-step-1-admin');
  // Per ogni step successivo, click "Avanti" (Salta dove non compilato)
  for (let i = 2; i <= 8; i++) {
    // Salta se c'è il pulsante, altrimenti click avanti
    const skip = await page.locator('button', { hasText: /Salta/i }).first();
    if (await skip.count() > 0) {
      await skip.click();
    } else {
      const next = await page.locator('button', { hasText: /Avanti|Salvo|Termina/i }).first();
      if (await next.count() > 0) await next.click();
    }
    await page.waitForTimeout(800);
    await snap(page, `18-2-step-${i}`);
  }

  // 3. Home / Wallet
  await page.goto(`${BASE}/`);
  await page.waitForLoadState('networkidle');
  await snap(page, '01-home');
  await page.goto(`${BASE}/wallet`);
  await page.waitForLoadState('networkidle');
  await snap(page, '10-wallet');

  // 4. Chat
  await page.goto(`${BASE}/chat`);
  await page.waitForLoadState('networkidle');
  await snap(page, '06-chat-empty');

  // 5. /me/memoria
  await page.goto(`${BASE}/me/memory`);
  await page.waitForLoadState('networkidle');
  await snap(page, '08-memoria');

  // 6. /me/integrazioni
  await page.goto(`${BASE}/me/integrazioni`);
  await page.waitForLoadState('networkidle');
  await snap(page, '16-integrazioni');

  // 7. /me/proposte
  await page.goto(`${BASE}/me/proposte`);
  await page.waitForLoadState('networkidle');
  await snap(page, '16-proposte');

  // 8. Tasks / Shopping / Notes
  for (const route of ['tasks', 'shopping', 'notes']) {
    await page.goto(`${BASE}/${route}`);
    await page.waitForLoadState('networkidle');
    await snap(page, `28-${route}`);
  }

  // 9. Admin pages
  for (const route of [
    'admin', 'admin/skills', 'admin/memory', 'admin/smart-home',
    'admin/proactivity', 'admin/devices', 'admin/diagnostics',
  ]) {
    await page.goto(`${BASE}/${route}`);
    await page.waitForLoadState('networkidle');
    await snap(page, `20-${route.replace(/\//g, '-')}`);
  }

  // 10. Pair page (anon — apri in nuovo context)
  const anonContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    ignoreHTTPSErrors: true,
  });
  const anonPage = await anonContext.newPage();
  await anonPage.goto(`${BASE}/pair`);
  await anonPage.waitForTimeout(2000); // attendi il codice 6 cifre
  await anonPage.screenshot({
    path: path.join(RAW_DIR, '15-3-pair-page.png'),
    fullPage: false,
  });
  console.log('✓ 15-3-pair-page.png');

  // 11. Settings
  await page.goto(`${BASE}/settings`);
  await page.waitForLoadState('networkidle');
  await snap(page, '05-settings');

  await browser.close();
})().catch(err => {
  console.error('Errore:', err);
  process.exit(1);
});
JS

echo "==> Esecuzione Playwright per screenshot..."
echo "BASE: $PWBASE"
echo "OUT:  $RAW_DIR"
echo

cd "$ROOT/frontend"

# Verifica che playwright sia installato
if [[ ! -d node_modules/@playwright/test ]]; then
  echo "Playwright non trovato. Installo..."
  npm install --no-save @playwright/test
  npx playwright install chromium
fi

PWBASE="$PWBASE" \
PW_ADMIN_EMAIL="$PW_ADMIN_EMAIL" \
PW_ADMIN_PASSWORD="$PW_ADMIN_PASSWORD" \
RAW_DIR="$RAW_DIR" \
  node "$PW_SCRIPT"

echo
echo "==> Ottimizzazione PNG (pngquant)..."
if command -v pngquant >/dev/null; then
  for f in "$RAW_DIR"/*.png; do
    [[ -f $f ]] || continue
    base=$(basename "$f")
    pngquant --quality=80-95 --strip --force \
      --output "$OUT_DIR/$base" "$f"
    echo "  ✓ $OUT_DIR/$base"
  done
else
  echo "  pngquant non installato → copia raw senza ottimizzare"
  cp -v "$RAW_DIR"/*.png "$OUT_DIR/"
fi

echo
echo "==> Done. Screenshot in $OUT_DIR/"
ls -1 "$OUT_DIR"/*.png 2>&1 | head -30
