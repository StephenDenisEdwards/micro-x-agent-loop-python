import { describe, expect, it, vi } from 'vitest';
import { ApiError, RestClient } from './rest';

function mockFetch(handler: (input: string, init?: RequestInit) => Response | Promise<Response>): typeof fetch {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    return handler(url, init);
  }) as unknown as typeof fetch;
}

describe('RestClient', () => {
  it('GET /api/health returns the parsed JSON body', async () => {
    const rest = new RestClient({
      baseUrl: 'http://srv',
      fetchImpl: mockFetch((url) => {
        expect(url).toBe('http://srv/api/health');
        return new Response(JSON.stringify({
          status: 'ok',
          active_sessions: 1,
          tools: 2,
          memory_enabled: true,
        }), { status: 200, headers: { 'content-type': 'application/json' } });
      }),
    });
    const h = await rest.health();
    expect(h.tools).toBe(2);
  });

  it('listSessions unwraps the { sessions } envelope', async () => {
    const rest = new RestClient({
      baseUrl: 'http://srv/',
      fetchImpl: mockFetch(() =>
        new Response(JSON.stringify({ sessions: [{ id: 's1', title: 'one' }] }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    });
    const list = await rest.listSessions();
    expect(list[0]!.id).toBe('s1');
  });

  it('createSession POSTs and returns the session id', async () => {
    const fetchSpy = vi.fn(async () =>
      new Response(JSON.stringify({ session_id: 'new-id' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );
    const rest = new RestClient({ baseUrl: 'http://srv', fetchImpl: fetchSpy as unknown as typeof fetch });
    const id = await rest.createSession();
    expect(id).toBe('new-id');
    expect(fetchSpy).toHaveBeenCalledWith(
      'http://srv/api/sessions',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('attaches Authorization when apiSecret is set', async () => {
    const fetchSpy = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      const headers = new Headers(init?.headers);
      expect(headers.get('authorization')).toBe('Bearer abc');
      return new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } });
    });
    const rest = new RestClient({
      baseUrl: 'http://srv',
      apiSecret: 'abc',
      fetchImpl: fetchSpy as unknown as typeof fetch,
    });
    await rest.health();
    expect(fetchSpy).toHaveBeenCalled();
  });

  it('throws ApiError on non-2xx responses', async () => {
    const rest = new RestClient({
      baseUrl: 'http://srv',
      fetchImpl: mockFetch(() =>
        new Response(JSON.stringify({ error: 'nope' }), {
          status: 400,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    });
    await expect(rest.health()).rejects.toBeInstanceOf(ApiError);
    await expect(rest.health()).rejects.toMatchObject({ status: 400, message: 'nope' });
  });

  it('getMessages maps role/content into ChatMessages', async () => {
    const rest = new RestClient({
      baseUrl: 'http://srv',
      fetchImpl: mockFetch(() =>
        new Response(
          JSON.stringify({
            messages: [
              { role: 'user', content: 'hello' },
              { role: 'assistant', content: 'hi back' },
              { role: 'tool', content: 'whatever' },
            ],
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        ),
      ),
    });
    const msgs = await rest.getMessages('sess');
    expect(msgs).toHaveLength(3);
    expect(msgs[0]!.role).toBe('user');
    expect(msgs[1]!.role).toBe('assistant');
    // Unknown roles fall back to system.
    expect(msgs[2]!.role).toBe('system');
  });
});
