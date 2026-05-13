/**
 * Vitest config — runs the lightweight unit suite for src/**.
 *
 * Excludes:
 *  - `e2e/**`  — Playwright suite, runs via `npm run test:e2e`
 *  - `node_modules/**` — pulled in transitively
 *
 * No DOM emulation here: every unit currently under test is pure logic
 * (descriptor math, permission gate, quality scoring). When a component
 * test arrives, switch `environment` to `jsdom` and add the corresponding
 * setup file.
 */

import { defineConfig } from 'vitest/config';


export default defineConfig({
  test: {
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    exclude: ['node_modules/**', 'e2e/**', 'dist/**'],
    environment: 'node',
  },
});
