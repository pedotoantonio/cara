/**
 * Pairing flow — anonymous device opens /pair, gets a 6-digit code.
 */
import { expect, test } from '@playwright/test';


test.describe('pair page', () => {
  test('unauthenticated /pair shows a 6-digit code', async ({ page }) => {
    await page.goto('/pair');
    // The code is rendered with tracking-widest so we just look for any
    // 6-digit text in the page.
    const code = page.locator('text=/^\\d{6}$/');
    await expect(code).toBeVisible({ timeout: 10_000 });

    // The instruction line is present.
    await expect(
      page.getByText(/admin\/devices/i).first(),
    ).toBeVisible();
  });
});
