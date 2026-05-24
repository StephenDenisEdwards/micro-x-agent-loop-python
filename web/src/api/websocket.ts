import type { ClientFrame, ServerFrame } from '../types/protocol';

export type WsStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'error';

export interface AgentWsConfig {
  url: string;
  /** WebSocket constructor — override for tests. */
  socketFactory?: (url: string) => WebSocketLike;
  /** Auto-reconnect with exponential backoff. */
  reconnect?: boolean;
  /** Initial reconnect delay in ms. */
  initialReconnectDelayMs?: number;
  /** Maximum reconnect delay in ms. */
  maxReconnectDelayMs?: number;
  /** Ping interval in ms; <=0 disables pings. */
  pingIntervalMs?: number;
  /** Logger hook. */
  onLog?: (level: 'info' | 'warn' | 'error', message: string) => void;
}

/**
 * Minimal WebSocket-like interface. The browser ``WebSocket`` matches this
 * shape; the in-memory test double in src/test/mock-ws.ts also implements it.
 */
export interface WebSocketLike {
  readonly readyState: number;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  addEventListener(type: 'open', listener: () => void): void;
  addEventListener(type: 'close', listener: (ev: { code: number; reason: string }) => void): void;
  addEventListener(type: 'error', listener: (ev: unknown) => void): void;
  addEventListener(type: 'message', listener: (ev: { data: string }) => void): void;
}

type Listener = (frame: ServerFrame) => void;
type StatusListener = (status: WsStatus) => void;

const OPEN = 1;

/**
 * Manages a single WebSocket connection to ``/api/ws/{session_id}``.
 *
 * Mirrors the protocol in src/micro_x_agent_loop/server/ws_channel.py. Buffers
 * outgoing frames while connecting, reconnects on transient errors, and emits
 * typed ``ServerFrame`` events to subscribers.
 */
export class AgentWebSocketClient {
  private readonly cfg: Required<Omit<AgentWsConfig, 'onLog'>> & { onLog: NonNullable<AgentWsConfig['onLog']> };
  private socket: WebSocketLike | null = null;
  private status: WsStatus = 'idle';
  private listeners = new Set<Listener>();
  private statusListeners = new Set<StatusListener>();
  private outbound: ClientFrame[] = [];
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private nextDelay: number;
  private intentionallyClosed = false;

  constructor(config: AgentWsConfig) {
    this.cfg = {
      url: config.url,
      socketFactory: config.socketFactory ?? defaultSocketFactory,
      reconnect: config.reconnect ?? true,
      initialReconnectDelayMs: config.initialReconnectDelayMs ?? 500,
      maxReconnectDelayMs: config.maxReconnectDelayMs ?? 8000,
      pingIntervalMs: config.pingIntervalMs ?? 25_000,
      onLog: config.onLog ?? (() => {}),
    };
    this.nextDelay = this.cfg.initialReconnectDelayMs;
  }

  get currentStatus(): WsStatus {
    return this.status;
  }

  connect(): void {
    if (this.status === 'connecting' || this.status === 'open') return;
    this.intentionallyClosed = false;
    this.setStatus('connecting');
    let sock: WebSocketLike;
    try {
      sock = this.cfg.socketFactory(this.cfg.url);
    } catch (err) {
      this.cfg.onLog('error', `WS factory failed: ${String(err)}`);
      this.setStatus('error');
      this.scheduleReconnect();
      return;
    }
    this.socket = sock;
    sock.addEventListener('open', () => this.handleOpen());
    sock.addEventListener('message', (ev) => this.handleMessage(ev.data));
    sock.addEventListener('error', () => this.handleError());
    sock.addEventListener('close', (ev) => this.handleClose(ev.code, ev.reason));
  }

  disconnect(): void {
    this.intentionallyClosed = true;
    this.clearTimers();
    if (this.socket) {
      try {
        this.socket.close(1000, 'client disconnect');
      } catch {
        /* ignore */
      }
    }
    this.socket = null;
    this.setStatus('closed');
  }

  send(frame: ClientFrame): void {
    if (this.socket && this.status === 'open' && this.socket.readyState === OPEN) {
      try {
        this.socket.send(JSON.stringify(frame));
        return;
      } catch (err) {
        this.cfg.onLog('warn', `Send failed, buffering: ${String(err)}`);
      }
    }
    this.outbound.push(frame);
    if (this.status === 'idle' || this.status === 'closed' || this.status === 'error') {
      this.connect();
    }
  }

  sendMessage(text: string): void {
    this.send({ type: 'message', text });
  }

  sendAnswer(questionId: string, text: string): void {
    this.send({ type: 'answer', question_id: questionId, text });
  }

  onFrame(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  onStatus(listener: StatusListener): () => void {
    this.statusListeners.add(listener);
    listener(this.status);
    return () => this.statusListeners.delete(listener);
  }

  // -- internals --

  private setStatus(s: WsStatus): void {
    if (this.status === s) return;
    this.status = s;
    for (const l of this.statusListeners) {
      try {
        l(s);
      } catch (err) {
        this.cfg.onLog('warn', `status listener threw: ${String(err)}`);
      }
    }
  }

  private handleOpen(): void {
    this.setStatus('open');
    this.nextDelay = this.cfg.initialReconnectDelayMs;
    // Flush buffered outbound frames.
    const queued = this.outbound.splice(0);
    for (const f of queued) {
      try {
        this.socket?.send(JSON.stringify(f));
      } catch (err) {
        this.cfg.onLog('warn', `flush failed: ${String(err)}`);
        this.outbound.unshift(f);
        break;
      }
    }
    if (this.cfg.pingIntervalMs > 0) {
      this.pingTimer = setInterval(() => {
        try {
          this.socket?.send(JSON.stringify({ type: 'ping' }));
        } catch {
          /* ignore */
        }
      }, this.cfg.pingIntervalMs);
    }
  }

  private handleMessage(raw: string): void {
    let frame: ServerFrame;
    try {
      frame = JSON.parse(raw) as ServerFrame;
    } catch (err) {
      this.cfg.onLog('warn', `bad frame: ${String(err)}`);
      return;
    }
    for (const l of this.listeners) {
      try {
        l(frame);
      } catch (err) {
        this.cfg.onLog('error', `frame listener threw: ${String(err)}`);
      }
    }
  }

  private handleError(): void {
    this.cfg.onLog('warn', 'WebSocket error');
    this.setStatus('error');
  }

  private handleClose(code: number, reason: string): void {
    this.cfg.onLog('info', `WS closed: code=${code} reason=${reason}`);
    this.clearTimers();
    this.socket = null;
    this.setStatus('closed');
    if (!this.intentionallyClosed && this.cfg.reconnect) {
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer || this.intentionallyClosed) return;
    const delay = this.nextDelay;
    this.nextDelay = Math.min(this.nextDelay * 2, this.cfg.maxReconnectDelayMs);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private clearTimers(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }
}

function defaultSocketFactory(url: string): WebSocketLike {
  return new WebSocket(url) as unknown as WebSocketLike;
}
