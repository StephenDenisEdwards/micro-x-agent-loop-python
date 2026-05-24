import type { Page } from '@playwright/test';
import type { ServerFrame } from '../src/types/protocol';

/**
 * Wait until the in-page mock harness has installed itself.
 */
export async function waitForMockReady(page: Page): Promise<void> {
  await page.waitForFunction(() => Boolean((window as unknown as { __E2E__?: unknown }).__E2E__));
}

/**
 * Push a frame into the mock WebSocket. Mirrors what the FastAPI server
 * would send via WebSocketChannel.
 */
export async function emitFrame(page: Page, frame: ServerFrame): Promise<void> {
  await page.evaluate((f) => {
    (window as unknown as { __E2E__: { emitFrame: (f: ServerFrame) => void } }).__E2E__.emitFrame(f);
  }, frame);
}

/** Read everything the page has sent over the (mock) WebSocket. */
export async function sentFrames(page: Page): Promise<string[]> {
  return page.evaluate(
    () =>
      (window as unknown as { __E2E__: { sentFrames: () => string[] } }).__E2E__.sentFrames(),
  );
}
