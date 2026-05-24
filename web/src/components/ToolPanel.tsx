import type { ToolEntry } from '../types/protocol';

interface ToolPanelProps {
  tools: ToolEntry[];
  hidden?: boolean;
}

const ARG_KEYS: Record<string, readonly string[]> = {
  web__web_fetch: ['url'],
  filesystem__bash: ['command'],
  filesystem__grep: ['pattern', 'path'],
  filesystem__read_file: ['path'],
  filesystem__glob: ['pattern', 'path'],
  filesystem__write_file: ['path'],
  filesystem__edit_file: ['path'],
  filesystem__delete_file: ['path'],
  google__gmail_search: ['query'],
  google__gmail_read: ['messageId'],
  playwright__browser_navigate: ['url'],
  playwright__browser_click: ['target'],
};

function shortenValue(v: unknown, limit = 32): string {
  const s = typeof v === 'string' ? v : JSON.stringify(v);
  return s.length <= limit ? s : `${s.slice(0, limit - 1)}…`;
}

export function summariseArgs(tool: string, input: Record<string, unknown> | null | undefined): string {
  if (!input) return '';
  const keys = ARG_KEYS[tool] ?? [];
  const parts: string[] = [];
  for (const k of keys) {
    if (input[k]) {
      parts.push(`${k}=${shortenValue(input[k])}`);
      if (parts.length >= 2) break;
    }
  }
  if (parts.length === 0) {
    for (const [k, v] of Object.entries(input)) {
      if (v !== null && v !== '' && !(Array.isArray(v) && v.length === 0)) {
        parts.push(`${k}=${shortenValue(v)}`);
        break;
      }
    }
  }
  return parts.join('  ');
}

export function formatDuration(ms: number | undefined): string {
  if (!ms || ms <= 0) return '';
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

export function formatSize(n: number | undefined): string {
  if (!n || n <= 0) return '';
  if (n < 1024) return `${n} chars`;
  if (n < 1024 * 1024) return `${Math.floor(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function ToolPanel({ tools, hidden }: ToolPanelProps): React.JSX.Element {
  return (
    <aside
      className={`tool-panel${hidden ? ' hidden' : ''}`}
      data-testid="tool-panel"
      aria-label="Tool executions"
    >
      <div className="panel-title">Tools</div>
      <ul className="tool-panel-list">
        {tools.length === 0 ? (
          <li className="tool-entry" data-testid="tool-empty">
            <span className="meta">No tools invoked yet.</span>
          </li>
        ) : null}
        {tools.map((t) => {
          const args = summariseArgs(t.name, t.input);
          const duration = formatDuration(t.durationMs);
          const size = formatSize(t.resultChars);
          const badges: string[] = [];
          if (t.wasTruncated) badges.push('trunc');
          if (t.wasSummarized) badges.push('summ');
          return (
            <li className="tool-entry" key={t.toolUseId} data-testid="tool-entry" data-status={t.status}>
              <div className="name">
                <span className={`status-${t.status}`}>
                  {t.status === 'running' ? '⋯' : t.status === 'ok' ? '✓' : '✕'}
                </span>{' '}
                {t.name}
                {duration ? <span className="meta"> {duration}</span> : null}
              </div>
              {args ? <div className="args">{args}</div> : null}
              {size || badges.length > 0 ? (
                <div className="meta">
                  {size ? `→ ${size}` : null}
                  {badges.length ? ` [${badges.join(' ')}]` : null}
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
