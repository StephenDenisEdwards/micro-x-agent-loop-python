interface KeyHintsProps {
  hints?: readonly { key: string; label: string }[];
}

const DEFAULT_HINTS = [
  { key: 'Ctrl+S', label: 'Sessions' },
  { key: 'Ctrl+T', label: 'Tools' },
  { key: 'Ctrl+L', label: 'Logs' },
  { key: 'Ctrl+P', label: 'Commands' },
  { key: 'Ctrl+D', label: 'Theme' },
  { key: 'Esc', label: 'Close modal' },
] as const;

export function KeyHints({ hints = DEFAULT_HINTS }: KeyHintsProps): React.JSX.Element {
  return (
    <div className="keyhints" data-testid="keyhints">
      {hints.map((h) => (
        <span key={h.key}>
          <strong>{h.key}</strong>:{h.label}
        </span>
      ))}
    </div>
  );
}
