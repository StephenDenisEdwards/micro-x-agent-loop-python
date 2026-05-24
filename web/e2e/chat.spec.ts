import { expect, test } from '@playwright/test';
import { emitFrame, sentFrames, waitForMockReady } from './helpers';

test.describe('chat flow', () => {
  test('boots, sends a message, and renders streaming response', async ({ page }) => {
    await page.goto('/');
    await waitForMockReady(page);

    await expect(page.getByTestId('app-header')).toContainText('MICRO-X AGENT');
    await expect(page.getByTestId('chat-log')).toBeVisible();
    await expect(page.getByTestId('status-indicator')).toContainText(/connecting|connected/i);

    // Type a message and submit via Enter.
    const input = page.getByTestId('prompt-input');
    await input.fill('hello world');
    await input.press('Enter');

    await expect(page.getByText('hello world')).toBeVisible();
    const sent = await sentFrames(page);
    expect(sent.some((f) => f.includes('"hello world"'))).toBe(true);

    // Stream an assistant reply.
    await emitFrame(page, { type: 'text_delta', text: 'Hi ' });
    await emitFrame(page, { type: 'text_delta', text: 'there!' });
    await emitFrame(page, { type: 'turn_complete', usage: {} });

    await expect(page.getByText('Hi there!')).toBeVisible();
  });

  test('shows tool start/complete entries in the tool panel', async ({ page }) => {
    await page.goto('/');
    await waitForMockReady(page);

    // Toolpanel starts empty.
    await expect(page.getByTestId('tool-empty')).toBeVisible();

    await emitFrame(page, {
      type: 'tool_started',
      tool_use_id: 't1',
      tool: 'filesystem__read_file',
      tool_input: { path: '/etc/hosts' },
    });
    await expect(page.getByTestId('tool-entry').first()).toContainText('filesystem__read_file');
    await expect(page.getByTestId('tool-entry').first()).toContainText('path=/etc/hosts');

    await emitFrame(page, {
      type: 'tool_completed',
      tool_use_id: 't1',
      tool: 'filesystem__read_file',
      error: false,
      result_chars: 4096,
      was_summarized: false,
      was_truncated: false,
      duration_ms: 120,
    });
    await expect(page.getByTestId('tool-entry').first()).toHaveAttribute('data-status', 'ok');
    await expect(page.getByTestId('tool-entry').first()).toContainText('4 KB');
  });

  test('handles ask_user modal: enter answer and verify frame is sent', async ({ page }) => {
    await page.goto('/');
    await waitForMockReady(page);

    await emitFrame(page, {
      type: 'question',
      id: 'q1',
      text: 'Proceed with the operation?',
      options: null,
    });

    await expect(page.getByTestId('ask-user-modal')).toBeVisible();
    await expect(page.getByTestId('ask-user-question')).toContainText('Proceed');

    await page.getByTestId('ask-user-input').fill('yes please');
    await page.getByTestId('ask-user-input').press('Enter');

    await expect(page.getByTestId('ask-user-modal')).toBeHidden();

    const sent = await sentFrames(page);
    expect(sent.some((f) => f.includes('"answer"') && f.includes('"yes please"'))).toBe(true);
  });

  test('ask_user modal with options renders option buttons', async ({ page }) => {
    await page.goto('/');
    await waitForMockReady(page);

    await emitFrame(page, {
      type: 'question',
      id: 'q1',
      text: 'Pick one',
      options: [
        { value: 'a', label: 'Option A' },
        { value: 'b', label: 'Option B' },
      ],
    });

    const buttons = page.getByTestId('ask-user-option');
    await expect(buttons).toHaveCount(2);
    await buttons.first().click();
    await expect(page.getByTestId('ask-user-modal')).toBeHidden();

    const sent = await sentFrames(page);
    expect(sent.some((f) => f.includes('"answer"') && f.includes('"a"'))).toBe(true);
  });

  test('shows error frame as an error message in chat', async ({ page }) => {
    await page.goto('/');
    await waitForMockReady(page);
    await emitFrame(page, { type: 'error', message: 'simulated failure' });
    await expect(page.locator('.message.error')).toContainText('simulated failure');
  });
});
