import { afterEach, describe, expect, it } from 'vitest';
import { resolveApiBaseUrl, wsUrlForSession } from './urls';

afterEach(() => {
  delete (window as unknown as { __AGENT_API_URL__?: string }).__AGENT_API_URL__;
});

describe('resolveApiBaseUrl', () => {
  it('uses window.__AGENT_API_URL__ when set', () => {
    (window as unknown as { __AGENT_API_URL__: string }).__AGENT_API_URL__ = 'http://override:9000/';
    expect(resolveApiBaseUrl()).toBe('http://override:9000');
  });

  it('falls back to window.location.origin', () => {
    expect(resolveApiBaseUrl()).toBe(window.location.origin);
  });
});

describe('wsUrlForSession', () => {
  it('produces a ws:// URL from an http base', () => {
    expect(wsUrlForSession('http://x:8321', 'abc')).toBe('ws://x:8321/api/ws/abc');
  });

  it('produces a wss:// URL from an https base', () => {
    expect(wsUrlForSession('https://x', 'abc')).toBe('wss://x/api/ws/abc');
  });

  it('encodes the session id', () => {
    expect(wsUrlForSession('http://x', 'a/b c')).toBe('ws://x/api/ws/a%2Fb%20c');
  });
});
