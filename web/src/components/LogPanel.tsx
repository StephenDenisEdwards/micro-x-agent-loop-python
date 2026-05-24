import { useEffect, useRef } from 'react';

export interface LogLine {
  id: string;
  text: string;
  ts: number;
}

interface LogPanelProps {
  lines: LogLine[];
  hidden?: boolean;
}

export function LogPanel({ lines, hidden }: LogPanelProps): React.JSX.Element {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [lines]);

  return (
    <div
      className={`log-panel${hidden ? ' hidden' : ''}`}
      data-testid="log-panel"
      ref={ref}
      aria-label="Logs"
    >
      {lines.length === 0 ? <div className="log-line">No log lines.</div> : null}
      {lines.map((l) => (
        <div className="log-line" key={l.id} data-testid="log-line">
          {l.text}
        </div>
      ))}
    </div>
  );
}
