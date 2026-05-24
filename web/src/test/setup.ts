import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => {
  cleanup();
});

// jsdom doesn't define ``crypto.randomUUID`` in older Node, but it's fine for
// ours. Polyfill scrollIntoView used by some libs.
if (!(window.HTMLElement.prototype as { scrollIntoView?: () => void }).scrollIntoView) {
  // eslint-disable-next-line @typescript-eslint/no-empty-function
  window.HTMLElement.prototype.scrollIntoView = () => {};
}
