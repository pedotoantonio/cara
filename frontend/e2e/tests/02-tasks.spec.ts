/**
 * Task CRUD round-trip: add → see in list → mark done → delete.
 */
import { expect, test } from './fixtures';


test.describe('tasks', () => {
  test('add → complete → delete', async ({ freshUserPage }) => {
    const { page } = freshUserPage;

    await page.goto('/tasks');
    await expect(page.getByRole('heading', { name: /task/i }).first()).toBeVisible();

    // The "new task" input is the first text/textarea on the page.
    const input = page.getByRole('textbox').first();
    const title = `pw-task-${Math.random().toString(36).slice(2, 8)}`;
    await input.fill(title);
    await input.press('Enter');

    // Item appears in the list.
    await expect(page.getByText(title)).toBeVisible({ timeout: 5_000 });

    // Toggle done — the row exposes a checkbox.
    const item = page.getByText(title).first();
    const row = item.locator('xpath=ancestor::*[self::li or self::div][1]');
    const checkbox = row.getByRole('checkbox').first();
    await checkbox.click();

    // Once completed, the row should either be visually crossed-out or
    // moved to a "fatte" section. We assert via the data-state if any,
    // otherwise just check the checkbox is still in the DOM.
    await expect(checkbox).toBeChecked();

    // Delete via API (UI delete varies by skin; using the API keeps the
    // smoke focused on the create+toggle path).
    const list = await page.request.get('/api/v1/tasks');
    if (list.ok()) {
      const arr = await list.json();
      const created = arr.find((t: { title: string }) => t.title === title);
      if (created) {
        await page.request.delete(`/api/v1/tasks/${created.id}`);
      }
    }
  });
});
