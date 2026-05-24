import type { SessionSummary } from '../types/protocol';

interface SessionSidebarProps {
  sessions: SessionSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  hidden?: boolean;
}

export function SessionSidebar({
  sessions,
  activeId,
  onSelect,
  onNew,
  hidden,
}: SessionSidebarProps): React.JSX.Element {
  return (
    <aside
      className={`session-sidebar${hidden ? ' hidden' : ''}`}
      data-testid="session-sidebar"
      aria-label="Sessions"
    >
      <div className="session-sidebar-header">
        <span>Sessions</span>
        <button onClick={onNew} data-testid="new-session-button" aria-label="New session">
          + New
        </button>
      </div>
      {sessions.length === 0 ? (
        <ul className="session-sidebar-list">
          <li>
            <span className="session-meta">No sessions yet.</span>
          </li>
        </ul>
      ) : (
        <ul className="session-sidebar-list">
          {sessions.map((s) => (
            <li
              key={s.id}
              className={s.id === activeId ? 'active' : ''}
              onClick={() => onSelect(s.id)}
              data-testid="session-item"
              data-session-id={s.id}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onSelect(s.id);
                }
              }}
            >
              <span className="session-title">{s.title || s.id.slice(0, 8)}</span>
              <span className="session-meta">
                {s.message_count != null ? `${s.message_count} msgs` : null}
              </span>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
