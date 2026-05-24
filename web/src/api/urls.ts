/**
 * Resolve the API base URL and WebSocket URL from environment / runtime.
 *
 * Priority order:
 *   1. window override (E2E tests inject ``window.__AGENT_API_URL__``)
 *   2. ``VITE_API_BASE_URL`` build-time env
 *   3. Same-origin (the Vite dev server proxies /api to the FastAPI backend).
 */
export function resolveApiBaseUrl(): string {
  if (typeof window !== 'undefined') {
    const override = (window as unknown as { __AGENT_API_URL__?: string }).__AGENT_API_URL__;
    if (override) return override.replace(/\/$/, '');
  }
  const env = import.meta.env.VITE_API_BASE_URL;
  if (env) return env.replace(/\/$/, '');
  if (typeof window !== 'undefined') return window.location.origin;
  return 'http://127.0.0.1:8321';
}

export function wsUrlForSession(baseUrl: string, sessionId: string): string {
  const base = baseUrl.replace(/\/$/, '');
  const wsBase = base.replace(/^http/, 'ws');
  return `${wsBase}/api/ws/${encodeURIComponent(sessionId)}`;
}
