/**
 * Smoke tests — the most basic happy path: app loads, login works,
 * shell mounts, we can navigate.
 */
import { expect, test } from './fixtures';


test.describe('smoke', () => {
  test('login screen renders + invalid credentials surface error', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText(/cara/i).first()).toBeVisible();
    await page.getByLabel(/email/i).first().fill('does-not-exist@example.com');
    await page.getByLabel(/password/i).first().fill('wrong-password');
    await page.getByRole('button', { name: /accedi/i }).click();
    await expect(page.getByText(/invalid|errat|incorrect/i)).toBeVisible({
      timeout: 5_000,
    });
  });

  test('logged-in user lands on home page', async ({ loggedInPage }) => {
    await expect(loggedInPage).toHaveURL(/\/$/);
    // The app shell exposes a navigation rail / strip.
    await expect(loggedInPage.getByRole('navigation').first()).toBeVisible();
  });

  test('manifest + service worker are reachable', async ({ page }) => {
    const manifest = await page.request.get('/manifest.webmanifest');
    expect(manifest.ok()).toBeTruthy();
    const json = await manifest.json();
    expect(json.name).toMatch(/cara/i);
    expect(json.icons.length).toBeGreaterThanOrEqual(2);
    expect(json.shortcuts).toBeDefined();
    expect(json.shortcuts.length).toBeGreaterThanOrEqual(2);

    const sw = await page.request.get('/sw.js');
    expect(sw.ok()).toBeTruthy();
  });

  test('CARA local CA is downloadable from /cara-ca.crt', async ({ page }) => {
    const r = await page.request.get('/cara-ca.crt');
    expect(r.ok()).toBeTruthy();
    const text = await r.text();
    expect(text).toContain('BEGIN CERTIFICATE');
  });
});
