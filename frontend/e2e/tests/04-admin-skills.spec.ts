/**
 * Admin Skill Factory page — verifies the page mounts, tabs work, and
 * the primitive catalog is visible.
 */
import { expect, test } from './fixtures';


test.describe('admin skills', () => {
  test('admin can reach /admin/skills and see tabs + catalog', async ({ loggedInPage }) => {
    await loggedInPage.goto('/admin/skills');
    await expect(
      loggedInPage.getByRole('heading', { name: /skill factory/i }),
    ).toBeVisible();

    // Three tabs render
    await expect(loggedInPage.getByRole('button', { name: /in attesa/i })).toBeVisible();
    await expect(loggedInPage.getByRole('button', { name: /attive/i })).toBeVisible();
    await expect(loggedInPage.getByRole('button', { name: /disabilitate/i })).toBeVisible();

    // Primitive catalog disclosure (collapsed by default)
    await expect(
      loggedInPage.getByText(/catalogo primitive disponibili/i),
    ).toBeVisible();

    // Open the catalog and verify it lists the generic primitives
    await loggedInPage.getByText(/catalogo primitive disponibili/i).click();
    await expect(loggedInPage.getByText(/extract_list/i)).toBeVisible();
    await expect(loggedInPage.getByText(/summarize/i)).toBeVisible();
    await expect(loggedInPage.getByText(/ask_user/i)).toBeVisible();
    await expect(loggedInPage.getByText(/read_url/i)).toBeVisible();
  });

  test('non-admin cannot reach /admin/skills', async ({ freshUserPage }) => {
    const { page } = freshUserPage;
    await page.goto('/admin/skills');
    // The router redirects non-admins away or the component shows nothing.
    // Either way: no Skill Factory heading and no admin skill list.
    await expect(
      page.getByRole('heading', { name: /skill factory/i }),
    ).toHaveCount(0, { timeout: 3_000 });
  });
});
