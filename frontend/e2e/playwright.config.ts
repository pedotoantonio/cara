import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for CARA frontend E2E.
 *
 * Targets the LIVE backend at https://192.168.1.23:8455 by default
 * (override via PWBASE env). Self-signed cert in dev → ignoreHTTPSErrors.
 *
 * Run from /opt/cara/frontend:
 *   npx playwright install chromium       # one-time, downloads ~140MB
 *   PWBASE=https://192.168.1.23:8455 \
 *     npx playwright test --config e2e/playwright.config.ts
 *
 * In CI / on a developer Mac:
 *   npx playwright test --config e2e/playwright.config.ts --headed
 */
export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  retries: 1,
  workers: 1,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: process.env.PWBASE ?? 'https://192.168.1.23:8455',
    ignoreHTTPSErrors: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    locale: 'it-IT',
    timezoneId: 'Europe/Rome',
  },
  projects: [
    {
      name: 'chromium-desktop',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'iphone-12',
      use: { ...devices['iPhone 12'] },
    },
  ],
});
