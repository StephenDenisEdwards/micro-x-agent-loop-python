interface HeaderProps {
  title: string;
  subtitle?: string;
}

export function Header({ title, subtitle }: HeaderProps): React.JSX.Element {
  return (
    <header className="app-header" data-testid="app-header">
      <span>{title}</span>
      {subtitle ? <span className="subtitle" data-testid="app-subtitle">— {subtitle}</span> : null}
    </header>
  );
}
