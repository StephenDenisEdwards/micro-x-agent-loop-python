import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { THEMES, type ThemeName } from '../hooks/useTheme';

export interface Command {
  id: string;
  name: string;
  description: string;
  /** If present, executed instead of dispatching the slash command to the agent. */
  action?: () => void;
}

const SLASH_COMMANDS: Command[] = [
  { id: 'help', name: '/help', description: 'Show available commands' },
  { id: 'cost', name: '/cost', description: 'Show session cost breakdown' },
  { id: 'cost-reconcile', name: '/cost reconcile', description: 'Reconcile costs with provider API' },
  { id: 'session', name: '/session', description: 'Show current session info' },
  { id: 'session-list', name: '/session list', description: 'List recent sessions' },
  { id: 'session-new', name: '/session new', description: 'Start a new session' },
  { id: 'session-fork', name: '/session fork', description: 'Fork the current session' },
  { id: 'tools-mcp', name: '/tools mcp', description: 'List loaded MCP tools' },
  { id: 'routing', name: '/routing', description: 'Show routing configuration' },
  { id: 'routing-tasks', name: '/routing tasks', description: 'Show task type statistics' },
  { id: 'routing-recent', name: '/routing recent', description: 'Show recent routing decisions' },
  { id: 'compact', name: '/compact', description: 'Force conversation compaction' },
  { id: 'memory', name: '/memory', description: 'Show user memory status' },
  { id: 'memory-list', name: '/memory list', description: 'List user memory files' },
  { id: 'debug-payload', name: '/debug show-api-payload', description: 'Show last API payload' },
  { id: 'tasks', name: '/tasks', description: 'Toggle task decomposition panel' },
  { id: 'codegen-list', name: '/codegen-task-list', description: 'List codegen tasks' },
];

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  onRunSlashCommand: (cmd: string) => void;
  onToggleTasks: () => void;
  onSetTheme: (t: ThemeName) => void;
}

interface RankedCommand {
  cmd: Command;
  score: number;
}

function rankCommands(query: string, commands: Command[]): RankedCommand[] {
  const q = query.trim().toLowerCase();
  if (!q) return commands.map((cmd) => ({ cmd, score: 1 }));
  const ranked: RankedCommand[] = [];
  for (const cmd of commands) {
    const haystack = `${cmd.name} ${cmd.description}`.toLowerCase();
    if (!haystack.includes(q)) continue;
    let score = 0;
    if (cmd.name.toLowerCase().startsWith(q)) score += 10;
    else if (cmd.name.toLowerCase().includes(q)) score += 5;
    if (cmd.description.toLowerCase().includes(q)) score += 1;
    ranked.push({ cmd, score });
  }
  return ranked.sort((a, b) => b.score - a.score);
}

export function CommandPalette({
  open,
  onClose,
  onRunSlashCommand,
  onToggleTasks,
  onSetTheme,
}: CommandPaletteProps): React.JSX.Element | null {
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const themeCommands: Command[] = useMemo(
    () =>
      THEMES.map((t) => ({
        id: `theme-${t}`,
        name: `Theme: ${t}`,
        description: `Switch to ${t} theme`,
        action: () => onSetTheme(t),
      })),
    [onSetTheme],
  );

  const allCommands = useMemo<Command[]>(() => {
    const slash = SLASH_COMMANDS.map((c) =>
      c.id === 'tasks' ? { ...c, action: onToggleTasks } : c,
    );
    return [...slash, ...themeCommands];
  }, [onToggleTasks, themeCommands]);

  const ranked = useMemo(() => rankCommands(query, allCommands), [query, allCommands]);

  useEffect(() => {
    if (open) {
      setQuery('');
      setActiveIndex(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  if (!open) return null;

  function runCommand(cmd: Command): void {
    if (cmd.action) cmd.action();
    else onRunSlashCommand(cmd.name);
    onClose();
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>): void {
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, ranked.length - 1));
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      const target = ranked[activeIndex];
      if (target) runCommand(target.cmd);
    }
  }

  return (
    <div
      className="modal-backdrop"
      data-testid="command-palette-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal
      aria-label="Command palette"
    >
      <div className="command-palette" data-testid="command-palette">
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type a command…"
          data-testid="command-palette-input"
          aria-label="Command query"
        />
        <ul role="listbox">
          {ranked.length === 0 ? (
            <li data-testid="command-palette-empty">No matches</li>
          ) : null}
          {ranked.map((r, idx) => (
            <li
              key={r.cmd.id}
              className={idx === activeIndex ? 'active' : ''}
              onClick={() => runCommand(r.cmd)}
              onMouseEnter={() => setActiveIndex(idx)}
              role="option"
              aria-selected={idx === activeIndex}
              data-testid="command-palette-item"
              data-command-id={r.cmd.id}
            >
              <span className="cmd-name">{r.cmd.name}</span>
              <span className="cmd-desc">{r.cmd.description}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export { SLASH_COMMANDS, rankCommands };
