/**
 * Shared Playwright fixtures.
 *
 * `loggedInPage` — a Page already authenticated as the persistent admin
 * user (defaults to the credentials in CLAUDE.md, override with
 * PW_ADMIN_EMAIL / PW_ADMIN_PASSWORD).
 *
 * `freshUserPage` — registers a brand-new user with a random email per
 * test, logs them in, returns the Page. Use for tests that need a
 * deterministic empty state.
 */
import { test as base, expect, type Page } from '@playwright/test';

const ADMIN_EMAIL = process.env.PW_ADMIN_EMAIL ?? 'pedotoa@gmail.com';
const ADMIN_PASSWORD = process.env.PW_ADMIN_PASSWORD ?? 'caracasa2026';


async function login(page: Page, email: string, password: string): Promise<void> {
  await page.goto('/');
  // The login form mounts immediately when no token is present.
  const emailField = page.getByLabel(/email/i).first();
  await emailField.fill(email);
  await page.getByLabel(/password/i).first().fill(password);
  await page.getByRole('button', { name: /accedi/i }).click();
  // Wait for the auth-gated app shell to mount.
  await expect(page.locator('[data-cara-shell]').or(
    page.getByRole('navigation').first(),
  )).toBeVisible({ timeout: 10_000 });
}


type Fixtures = {
  loggedInPage: Page;
  freshUserPage: { page: Page; email: string; password: string };
};


export const test = base.extend<Fixtures>({
  loggedInPage: async ({ page }, use) => {
    await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    await use(page);
  },

  freshUserPage: async ({ page, request }, use) => {
    const random = Math.random().toString(36).slice(2, 10);
    const email = `pw-${random}@example.com`;
    const password = 'pw-strong-pass-1';

    // Register via API to keep the test fast and deterministic.
    const reg = await request.post('/api/v1/auth/register', {
      data: { email, password, full_name: `Playwright ${random}` },
    });
    if (!reg.ok()) {
      throw new Error(`register failed ${reg.status()}: ${await reg.text()}`);
    }
    await login(page, email, password);
    await use({ page, email, password });
  },
});

export { expect };
