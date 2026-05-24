import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { AgentWebSocketClient } from './websocket';
import { createMockWsFactory } from '../test/mock-ws';

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('AgentWebSocketClient', () => {
  it('emits status transitions and connects via the factory', async () => {
    const factory = createMockWsFactory(false);
    const statuses: string[] = [];
    const client = new AgentWebSocketClient({
      url: 'ws://x/api/ws/s1',
      socketFactory: factory,
      reconnect: false,
      pingIntervalMs: 0,
    });
    client.onStatus((s) => statuses.push(s));
    client.connect();
    expect(statuses).toEqual(['idle', 'connecting']);
    factory.last()!.emitOpen();
    expect(statuses.at(-1)).toBe('open');
  });

  it('dispatches inbound JSON frames to listeners', async () => {
    const factory = createMockWsFactory(true);
    const received: unknown[] = [];
    const client = new AgentWebSocketClient({
      url: 'ws://x/api/ws/s1',
      socketFactory: factory,
      reconnect: false,
      pingIntervalMs: 0,
    });
    client.onFrame((f) => received.push(f));
    client.connect();
    await vi.runAllTicks();
    factory.last()!.emitFrame({ type: 'text_delta', text: 'abc' });
    expect(received).toEqual([{ type: 'text_delta', text: 'abc' }]);
  });

  it('buffers outbound frames sent before open then flushes on open', async () => {
    const factory = createMockWsFactory(false);
    const client = new AgentWebSocketClient({
      url: 'ws://x/api/ws/s1',
      socketFactory: factory,
      reconnect: false,
      pingIntervalMs: 0,
    });
    client.sendMessage('queued-1');
    client.sendMessage('queued-2');
    // Factory created socket but didn't open it; nothing should be sent yet.
    expect(factory.last()!.sent).toEqual([]);
    factory.last()!.emitOpen();
    expect(factory.last()!.sent).toEqual([
      JSON.stringify({ type: 'message', text: 'queued-1' }),
      JSON.stringify({ type: 'message', text: 'queued-2' }),
    ]);
  });

  it('sends immediately once open', async () => {
    const factory = createMockWsFactory(false);
    const client = new AgentWebSocketClient({
      url: 'ws://x/api/ws/s1',
      socketFactory: factory,
      reconnect: false,
      pingIntervalMs: 0,
    });
    client.connect();
    factory.last()!.emitOpen();
    client.sendAnswer('q1', 'yes');
    expect(factory.last()!.sent).toEqual([
      JSON.stringify({ type: 'answer', question_id: 'q1', text: 'yes' }),
    ]);
  });

  it('reconnects with exponential backoff after an unexpected close', () => {
    const factory = createMockWsFactory(false);
    const client = new AgentWebSocketClient({
      url: 'ws://x/api/ws/s1',
      socketFactory: factory,
      reconnect: true,
      initialReconnectDelayMs: 100,
      maxReconnectDelayMs: 800,
      pingIntervalMs: 0,
    });
    client.connect();
    expect(factory.sockets.length).toBe(1);
    factory.last()!.emitClose(1006, 'abnormal');
    vi.advanceTimersByTime(100);
    expect(factory.sockets.length).toBe(2);
    factory.last()!.emitClose(1006, 'abnormal');
    vi.advanceTimersByTime(199);
    expect(factory.sockets.length).toBe(2);
    vi.advanceTimersByTime(1);
    expect(factory.sockets.length).toBe(3);
  });

  it('does not reconnect after an intentional disconnect', () => {
    const factory = createMockWsFactory(true);
    const client = new AgentWebSocketClient({
      url: 'ws://x/api/ws/s1',
      socketFactory: factory,
      reconnect: true,
      initialReconnectDelayMs: 50,
      pingIntervalMs: 0,
    });
    client.connect();
    vi.runAllTicks();
    client.disconnect();
    vi.advanceTimersByTime(10_000);
    expect(factory.sockets.length).toBe(1);
  });

  it('sends ping frames on the configured interval', () => {
    const factory = createMockWsFactory(false);
    const client = new AgentWebSocketClient({
      url: 'ws://x/api/ws/s1',
      socketFactory: factory,
      reconnect: false,
      pingIntervalMs: 1000,
    });
    client.connect();
    factory.last()!.emitOpen();
    vi.advanceTimersByTime(2500);
    const pings = factory.last()!.sent.filter((s) => s.includes('ping'));
    expect(pings.length).toBeGreaterThanOrEqual(2);
  });

  it('logs and tolerates malformed frames', () => {
    const factory = createMockWsFactory(true);
    const log = vi.fn();
    const client = new AgentWebSocketClient({
      url: 'ws://x/api/ws/s1',
      socketFactory: factory,
      reconnect: false,
      pingIntervalMs: 0,
      onLog: log,
    });
    const received: unknown[] = [];
    client.onFrame((f) => received.push(f));
    client.connect();
    vi.runAllTicks();
    factory.last()!.emitRaw('not-json');
    expect(received).toEqual([]);
    expect(log).toHaveBeenCalledWith('warn', expect.stringContaining('bad frame'));
  });

  it('sets status to error if the factory throws', () => {
    const bad = (() => {
      throw new Error('boom');
    }) as unknown as ConstructorParameters<typeof AgentWebSocketClient>[0]['socketFactory'];
    const log = vi.fn();
    const client = new AgentWebSocketClient({
      url: 'ws://x/api/ws/s1',
      socketFactory: bad,
      reconnect: false,
      pingIntervalMs: 0,
      onLog: log,
    });
    const statuses: string[] = [];
    client.onStatus((s) => statuses.push(s));
    client.connect();
    expect(statuses).toContain('error');
    expect(log).toHaveBeenCalledWith('error', expect.stringContaining('WS factory failed'));
  });
});
