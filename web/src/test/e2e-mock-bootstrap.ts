/**
 * Lightweight in-page mock harness used by Playwright. When the Vite build
 * sees ``VITE_E2E_MOCK_WS=1``, this module installs a stub ``fetch`` and a
 * stub ``WebSocket`` on ``window``. Playwright drives both via the
 * ``window.__E2E__`` API attached below.
 */

import type { ServerFrame, SessionSummary } from '../types/protocol';

type FetchInit = RequestInit | undefined;

interface E2EState {
  sessions: SessionSummary[];
  socket: E2EMockSocket | null;
}

class E2EMockSocket {
  static readonly OPEN = 1;
  readonly url: string;
  readyState = 0;
  readonly sent: string[] = [];
  private listeners: Record<string, Array<(ev: unknown) => void>> = {
    open: [], close: [], error: [], message: [],
  };

  constructor(url: string) {
    this.url = url;
    setTimeout(() => {
      this.readyState = E2EMockSocket.OPEN;
      this.fire('open');
    }, 0);
  }

  addEventListener(type: string, listener: (ev: unknown) => void): void {
    (this.listeners[type] ??= []).push(listener);
  }

  removeEventListener(type: string, listener: (ev: unknown) => void): void {
    const arr = this.listeners[type];
    if (!arr) return;
    const idx = arr.indexOf(listener);
    if (idx >= 0) arr.splice(idx, 1);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = 3;
    this.fire('close', { code: 1000, reason: '' });
  }

  emitFrame(frame: ServerFrame): void {
    const data = JSON.stringify(frame);
    this.fire('message', { data });
  }

  fire(type: string, ev?: unknown): void {
    for (const l of this.listeners[type] ?? []) l(ev);
  }
}

export function installMockWsForE2E(): void {
  const state: E2EState = {
    sessions: [
      { id: 'session-alpha', title: 'Alpha demo', message_count: 0 },
    ],
    socket: null,
  };

  const originalFetch = globalThis.fetch?.bind(globalThis);

  async function mockFetch(input: RequestInfo | URL, init?: FetchInit): Promise<Response> {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    const method = init?.method ?? 'GET';
    if (url.endsWith('/api/health')) {
      return jsonResponse({
        status: 'ok',
        active_sessions: state.sessions.length,
        tools: 3,
        memory_enabled: true,
      });
    }
    if (url.endsWith('/api/sessions') && method === 'GET') {
      return jsonResponse({ sessions: state.sessions });
    }
    if (url.endsWith('/api/sessions') && method === 'POST') {
      const id = `session-${Date.now()}`;
      state.sessions = [{ id, title: 'New session', message_count: 0 }, ...state.sessions];
      return jsonResponse({ session_id: id });
    }
    const messagesMatch = url.match(/\/api\/sessions\/([^/]+)\/messages$/);
    if (messagesMatch && method === 'GET') {
      return jsonResponse({ session_id: messagesMatch[1], messages: [] });
    }
    if (originalFetch) return originalFetch(input, init);
    return new Response('Not Found', { status: 404 });
  }

  globalThis.fetch = mockFetch as unknown as typeof fetch;

  // Monkey-patch WebSocket so the real client uses our mock.
  const originalWs = globalThis.WebSocket;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).WebSocket = function (url: string) {
    const sock = new E2EMockSocket(url);
    state.socket = sock;
    return sock;
  };
  // Restore on unload to be polite.
  window.addEventListener('beforeunload', () => {
    globalThis.fetch = originalFetch as typeof fetch;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (globalThis as any).WebSocket = originalWs;
  });

  // Public test API.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (window as any).__E2E__ = {
    emitFrame(frame: ServerFrame) {
      state.socket?.emitFrame(frame);
    },
    sentFrames(): string[] {
      return state.socket ? [...state.socket.sent] : [];
    },
    addSession(s: SessionSummary) {
      state.sessions = [s, ...state.sessions];
    },
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
