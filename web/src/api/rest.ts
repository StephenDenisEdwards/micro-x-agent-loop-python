import type { ChatMessage, HealthInfo, SessionSummary } from '../types/protocol';

export interface RestClientConfig {
  baseUrl: string;
  apiSecret?: string;
  fetchImpl?: typeof fetch;
}

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

/**
 * Thin REST client over the FastAPI server defined in
 * src/micro_x_agent_loop/server/app.py.
 */
export class RestClient {
  private readonly baseUrl: string;
  private readonly apiSecret: string | undefined;
  private readonly fetchImpl: typeof fetch;

  constructor(config: RestClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, '');
    this.apiSecret = config.apiSecret;
    this.fetchImpl = config.fetchImpl ?? globalThis.fetch.bind(globalThis);
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    if (this.apiSecret) {
      headers.set('Authorization', `Bearer ${this.apiSecret}`);
    }
    if (init.body && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
    const resp = await this.fetchImpl(`${this.baseUrl}${path}`, { ...init, headers });
    const ct = resp.headers.get('content-type') ?? '';
    const text = await resp.text();
    const body: unknown = text && ct.includes('application/json') ? JSON.parse(text) : text;
    if (!resp.ok) {
      const msg =
        typeof body === 'object' && body !== null && 'error' in body
          ? String((body as { error: unknown }).error)
          : text || resp.statusText;
      throw new ApiError(resp.status, msg);
    }
    return body as T;
  }

  health(): Promise<HealthInfo> {
    return this.request<HealthInfo>('/api/health');
  }

  async listSessions(): Promise<SessionSummary[]> {
    const body = await this.request<{ sessions: SessionSummary[] }>('/api/sessions');
    return body.sessions ?? [];
  }

  async createSession(): Promise<string> {
    const body = await this.request<{ session_id: string }>('/api/sessions', {
      method: 'POST',
    });
    return body.session_id;
  }

  async getMessages(sessionId: string): Promise<ChatMessage[]> {
    const body = await this.request<{ messages: { role: string; content: unknown }[] }>(
      `/api/sessions/${encodeURIComponent(sessionId)}/messages`,
    );
    return (body.messages ?? []).map((m, idx) => ({
      id: `${sessionId}-history-${idx}`,
      role: normalizeRole(m.role),
      text: flattenContent(m.content),
    }));
  }

  async deleteSession(sessionId: string): Promise<void> {
    await this.request(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
    });
  }
}

function normalizeRole(role: string): ChatMessage['role'] {
  if (role === 'user' || role === 'assistant' || role === 'system') return role;
  return 'system';
}

// Server history stores ``content`` as either a plain string or an Anthropic-style
// content-block list (e.g. ``[{type: "text", text: "..."}, {type: "tool_use", ...}]``).
// Flatten to a single string for the chat view; non-text blocks become a short marker.
function flattenContent(content: unknown): string {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) return content.map(blockToText).join('');
  if (content && typeof content === 'object') return blockToText(content);
  return content == null ? '' : String(content);
}

function blockToText(block: unknown): string {
  if (typeof block === 'string') return block;
  if (!block || typeof block !== 'object') return '';
  const b = block as { type?: string; text?: unknown; name?: unknown; content?: unknown };
  if (b.type === 'text' && typeof b.text === 'string') return b.text;
  if (b.type === 'tool_use' && typeof b.name === 'string') return `\n[tool_use: ${b.name}]\n`;
  if (b.type === 'tool_result') return `\n[tool_result]\n${flattenContent(b.content)}\n`;
  if (typeof b.text === 'string') return b.text;
  return '';
}
