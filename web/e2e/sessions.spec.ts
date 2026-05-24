import { expect, test } from '@playwright/test';
import { waitForMockReady } from './helpers';

test.describe('session management', () => {
  test('the seeded demo session appears in the sidebar', async ({ page }) => {
    await page.goto('/');
    await waitForMockReady(page);
    const items = page.getByTestId('session-item');
    await expect(items).toHaveCount(1);
    await expect(items.first()).toContainText('Alpha demo');
  });

  test('clicking + New creates and selects a new session', async ({ page }) => {
    await page.goto('/');
    await waitForMockReady(page);

    await page.getByTestId('new-session-button').click();

    const items = page.getByTestId('session-item');
    await expect(items).toHaveCount(2);
    // Newest is prepended, and becomes active.
    await expect(items.first()).toHaveClass(/active/);
  });
});
