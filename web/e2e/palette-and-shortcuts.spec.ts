import { expect, test } from '@playwright/test';
import { sentFrames, waitForMockReady } from './helpers';

test.describe('command palette and keyboard shortcuts', () => {
  test('Ctrl+P opens the command palette; type, Enter dispatches a slash command', async ({ page }) => {
    await page.goto('/');
    await waitForMockReady(page);

    await page.keyboard.press('Control+P');
    await expect(page.getByTestId('command-palette')).toBeVisible();
    await page.getByTestId('command-palette-input').fill('/help');
    await page.keyboard.press('Enter');

    await expect(page.getByTestId('command-palette')).toBeHidden();
    const sent = await sentFrames(page);
    expect(sent.some((f) => f.includes('"/help"'))).toBe(true);
  });

  test('Escape closes the palette without running anything', async ({ page }) => {
    await page.goto('/');
    await waitForMockReady(page);
    await page.keyboard.press('Control+P');
    await expect(page.getByTestId('command-palette')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('command-palette')).toBeHidden();
  });

  test('Theme: ... command switches the html data-theme attribute', async ({ page }) => {
    await page.goto('/');
    await waitForMockReady(page);

    await page.keyboard.press('Control+P');
    await page.getByTestId('command-palette-input').fill('theme: dracula');
    await page.keyboard.press('Enter');

    await expect.poll(async () => page.evaluate(() => document.documentElement.dataset.theme)).toBe(
      'dracula',
    );
  });

  test('Ctrl+S toggles the session sidebar', async ({ page }) => {
    await page.goto('/');
    await waitForMockReady(page);
    const sidebar = page.getByTestId('session-sidebar');
    await expect(sidebar).toBeVisible();
    await page.keyboard.press('Control+S');
    await expect(sidebar).toBeHidden();
    await page.keyboard.press('Control+S');
    await expect(sidebar).toBeVisible();
  });

  test('Ctrl+T toggles the tool panel', async ({ page }) => {
    await page.goto('/');
    await waitForMockReady(page);
    const panel = page.getByTestId('tool-panel');
    await expect(panel).toBeVisible();
    await page.keyboard.press('Control+T');
    await expect(panel).toBeHidden();
  });

  test('Ctrl+L toggles the log panel', async ({ page }) => {
    await page.goto('/');
    await waitForMockReady(page);
    const log = page.getByTestId('log-panel');
    await expect(log).toBeHidden();
    await page.keyboard.press('Control+L');
    await expect(log).toBeVisible();
  });
});
