/**
 * PWA install prompt — verifies the user-facing flow:
 *   - the banner appears (native or fallback)
 *   - the Settings page exposes the manual re-trigger button
 *   - the cert install instructions are present
 */
import { expect, test } from './fixtures';


test.describe('pwa install', () => {
  test('install button on Settings re-opens the prompt', async ({ loggedInPage }) => {
    await loggedInPage.goto('/settings');
    await expect(
      loggedInPage.getByRole('button', { name: /installa cara come app/i }),
    ).toBeVisible();
  });

  test('Settings shows version + cert install instructions', async ({ loggedInPage }) => {
    await loggedInPage.goto('/settings');
    // Version stamp landed via define
    await expect(loggedInPage.getByText(/versione/i).first()).toBeVisible();
    // CA cert section
    await expect(
      loggedInPage.getByText(/certificato di sicurezza/i).first(),
    ).toBeVisible();
    // Toggle the details and check the download link is there
    await loggedInPage
      .getByText(/certificato di sicurezza/i).first()
      .click();
    await expect(
      loggedInPage.getByRole('link', { name: /scarica certificato cara/i }),
    ).toBeVisible();
  });

  test('clicking install button surfaces banner', async ({ loggedInPage }) => {
    await loggedInPage.goto('/settings');
    await loggedInPage
      .getByRole('button', { name: /installa cara come app/i })
      .click();
    // The banner has role=dialog and a recognisable title
    const banner = loggedInPage.getByRole('dialog').filter({
      hasText: /installa|aggiungi/i,
    });
    await expect(banner.first()).toBeVisible({ timeout: 3_000 });
  });
});
