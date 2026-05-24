import type { ServerFrame } from '../types/protocol';
import type { WebSocketLike } from '../api/websocket';

type Listeners = {
  open: Array<() => void>;
  close: Array<(ev: { code: number; reason: string }) => void>;
  error: Array<(ev: unknown) => void>;
  message: Array<(ev: { data: string }) => void>;
};

/**
 * In-memory WebSocket double. Calls to ``send`` are captured in ``sent``;
 * tests trigger ``emitFrame`` / ``emitOpen`` / ``emitClose`` to drive the
 * client through its lifecycle.
 */
export class MockWebSocket implements WebSocketLike {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readyState: number = MockWebSocket.CONNECTING;
  readonly url: string;
  readonly sent: string[] = [];
  private listeners: Listeners = { open: [], close: [], error: [], message: [] };

  constructor(url: string) {
    this.url = url;
  }

  addEventListener(type: 'open', listener: () => void): void;
  addEventListener(type: 'close', listener: (ev: { code: number; reason: string }) => void): void;
  addEventListener(type: 'error', listener: (ev: unknown) => void): void;
  addEventListener(type: 'message', listener: (ev: { data: string }) => void): void;
  addEventListener(type: keyof Listeners, listener: (...args: never[]) => void): void {
    (this.listeners[type] as Array<typeof listener>).push(listener);
  }

  send(data: string): void {
    if (this.readyState !== MockWebSocket.OPEN) {
      throw new Error(`MockWebSocket.send while readyState=${this.readyState}`);
    }
    this.sent.push(data);
  }

  close(code = 1000, reason = ''): void {
    if (this.readyState === MockWebSocket.CLOSED) return;
    this.readyState = MockWebSocket.CLOSED;
    for (const l of this.listeners.close) l({ code, reason });
  }

  emitOpen(): void {
    this.readyState = MockWebSocket.OPEN;
    for (const l of this.listeners.open) l();
  }

  emitFrame(frame: ServerFrame): void {
    const data = JSON.stringify(frame);
    for (const l of this.listeners.message) l({ data });
  }

  emitRaw(data: string): void {
    for (const l of this.listeners.message) l({ data });
  }

  emitError(err?: unknown): void {
    for (const l of this.listeners.error) l(err ?? new Error('mock error'));
  }

  emitClose(code = 1006, reason = 'abnormal'): void {
    this.readyState = MockWebSocket.CLOSED;
    for (const l of this.listeners.close) l({ code, reason });
  }
}

/** A factory that records every socket it constructs. */
export interface MockWsFactory {
  (url: string): MockWebSocket;
  /** All sockets created via this factory, in construction order. */
  sockets: MockWebSocket[];
  /** Convenience helper to grab the most recently created socket. */
  last(): MockWebSocket | undefined;
}

export function createMockWsFactory(autoOpen = true): MockWsFactory {
  const sockets: MockWebSocket[] = [];
  const factory = ((url: string): MockWebSocket => {
    const sock = new MockWebSocket(url);
    sockets.push(sock);
    if (autoOpen) {
      // Emulate the browser's async open in a microtask.
      queueMicrotask(() => sock.emitOpen());
    }
    return sock;
  }) as MockWsFactory;
  factory.sockets = sockets;
  factory.last = () => sockets[sockets.length - 1];
  return factory;
}
