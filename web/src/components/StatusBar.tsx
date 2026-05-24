import type { WsStatus } from '../api/websocket';

interface StatusBarProps {
  status: WsStatus;
  model: string;
  sessionId: string | null;
  turnInFlight: boolean;
  usage?: Record<string, unknown> | null;
}

function statusLabel(s: WsStatus): string {
  switch (s) {
    case 'open': return 'connected';
    case 'connecting': return 'connecting…';
    case 'closed': return 'disconnected';
    case 'error': return 'error';
    case 'idle': return 'idle';
  }
}

function extractCost(usage: Record<string, unknown> | null | undefined): string | null {
  if (!usage) return null;
  const cost = usage['cost_usd'];
  if (typeof cost === 'number') return `$${cost.toFixed(4)}`;
  const total = usage['total_cost'];
  if (typeof total === 'number') return `$${total.toFixed(4)}`;
  return null;
}

function extractTokens(usage: Record<string, unknown> | null | undefined): string | null {
  if (!usage) return null;
  const inT = usage['input_tokens'];
  const outT = usage['output_tokens'];
  if (typeof inT === 'number' && typeof outT === 'number') return `${inT}→${outT} tok`;
  return null;
}

export function StatusBar({
  status,
  model,
  sessionId,
  turnInFlight,
  usage,
}: StatusBarProps): React.JSX.Element {
  const cost = extractCost(usage);
  const tokens = extractTokens(usage);
  return (
    <div className="status-bar" data-testid="status-bar" role="status">
      <span className="indicator" data-testid="status-indicator">
        <span className={`dot ${status}`} aria-hidden />
        {statusLabel(status)}
      </span>
      <span>model: {model || '—'}</span>
      <span>session: {sessionId ? sessionId.slice(0, 8) : 'none'}</span>
      {turnInFlight ? <span data-testid="status-busy">⟳ running…</span> : null}
      {tokens ? <span data-testid="status-tokens">{tokens}</span> : null}
      {cost ? <span data-testid="status-cost">{cost}</span> : null}
    </div>
  );
}
