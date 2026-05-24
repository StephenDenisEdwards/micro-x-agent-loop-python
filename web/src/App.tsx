import { useCallback, useEffect, useMemo, useState } from 'react';
import { RestClient } from './api/rest';
import { resolveApiBaseUrl } from './api/urls';
import { useAgentSession } from './hooks/useAgentSession';
import { useTheme } from './hooks/useTheme';
import type { WebSocketLike } from './api/websocket';
import type { HealthInfo, SessionSummary } from './types/protocol';
import { ChatLog } from './components/ChatLog';
import { ToolPanel } from './components/ToolPanel';
import { SessionSidebar } from './components/SessionSidebar';
import { StatusBar } from './components/StatusBar';
import { PromptInput } from './components/PromptInput';
import { AskUserModal } from './components/AskUserModal';
import { CommandPalette } from './components/CommandPalette';
import { Header } from './components/Header';
import { KeyHints } from './components/KeyHints';
import { LogPanel, type LogLine } from './components/LogPanel';

const STARTUP_BANNER = `  ███╗   ███╗██╗ ██████╗██████╗  ██████╗     ██╗  ██╗
  ████╗ ████║██║██╔════╝██╔══██╗██╔═══██╗    ╚██╗██╔╝
  ██╔████╔██║██║██║     ██████╔╝██║   ██║█████╗╚███╔╝
  ██║╚██╔╝██║██║██║     ██╔══██╗██║   ██║╚════╝██╔██╗
  ██║ ╚═╝ ██║██║╚██████╗██║  ██║╚██████╔╝    ██╔╝ ██╗
  ╚═╝     ╚═╝╚═╝ ╚═════╝╚═╝  ╚═╝ ╚═════╝    ╚═╝  ╚═╝
        █████╗  ██████╗ ███████╗███╗   ██╗████████╗
       ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝
       ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║
       ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║
       ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║
       ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝
                          AI`;

export interface AppProps {
  /** Override the REST client (for tests). */
  restClient?: RestClient;
  /** Override the WebSocket factory (for tests / Playwright). */
  socketFactory?: (url: string) => WebSocketLike;
  /** Override base URL resolution (for tests). */
  baseUrl?: string;
}

export function App({ restClient, socketFactory, baseUrl }: AppProps = {}): React.JSX.Element {
  const resolvedBaseUrl = useMemo(() => baseUrl ?? resolveApiBaseUrl(), [baseUrl]);
  const rest = useMemo(
    () => restClient ?? new RestClient({ baseUrl: resolvedBaseUrl }),
    [restClient, resolvedBaseUrl],
  );

  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [showSessions, setShowSessions] = useState(true);
  const [showTools, setShowTools] = useState(true);
  const [showLogs, setShowLogs] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [logLines, setLogLines] = useState<LogLine[]>([]);
  const [bootError, setBootError] = useState<string | null>(null);

  const { theme, setTheme, toggle: toggleTheme } = useTheme();

  const session = useAgentSession({
    baseUrl: resolvedBaseUrl,
    sessionId: activeSessionId,
    socketFactory,
  });

  // Boot: hit /api/health and load sessions. Runs once per RestClient — we
  // intentionally don't depend on activeSessionId so user-initiated changes
  // don't clobber an in-memory session list update.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [h, list] = await Promise.all([rest.health(), rest.listSessions()]);
        if (cancelled) return;
        setHealth(h);
        setSessions(list);
        setActiveSessionId((curr) => curr ?? list[0]?.id ?? null);
      } catch (err) {
        if (cancelled) return;
        setBootError(err instanceof Error ? err.message : String(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [rest]);

  // When the active session changes, load history.
  useEffect(() => {
    if (!activeSessionId) return;
    let cancelled = false;
    (async () => {
      try {
        const messages = await rest.getMessages(activeSessionId);
        if (!cancelled) session.loadHistory(messages);
      } catch {
        /* a session with no history is fine */
      }
    })();
    return () => {
      cancelled = true;
    };
    // session.loadHistory is stable from useCallback.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSessionId, rest]);

  // Append system_message and error frames as log lines for the log panel.
  useEffect(() => {
    const last = session.state.messages.at(-1);
    if (!last) return;
    if (last.role !== 'system' && last.role !== 'error') return;
    setLogLines((prev) => [
      ...prev,
      { id: last.id, text: `[${last.role}] ${last.text}`, ts: Date.now() },
    ].slice(-500));
  }, [session.state.messages]);

  const newSession = useCallback(async () => {
    try {
      const id = await rest.createSession();
      setActiveSessionId(id);
      setSessions((prev) => [{ id, title: null, message_count: 0 }, ...prev]);
    } catch (err) {
      setBootError(err instanceof Error ? err.message : String(err));
    }
  }, [rest]);

  const selectSession = useCallback((id: string) => {
    setActiveSessionId(id);
  }, []);

  const runSlash = useCallback(
    (cmd: string) => {
      session.sendMessage(cmd);
    },
    [session],
  );

  // Keyboard shortcuts.
  useEffect(() => {
    function handler(e: KeyboardEvent): void {
      if (e.ctrlKey || e.metaKey) {
        switch (e.key.toLowerCase()) {
          case 'p':
            e.preventDefault();
            setPaletteOpen((v) => !v);
            return;
          case 's':
            e.preventDefault();
            setShowSessions((v) => !v);
            return;
          case 't':
            e.preventDefault();
            setShowTools((v) => !v);
            return;
          case 'l':
            e.preventDefault();
            setShowLogs((v) => !v);
            return;
          case 'd':
            e.preventDefault();
            toggleTheme();
            return;
        }
      }
      if (e.key === 'Escape') {
        if (paletteOpen) {
          setPaletteOpen(false);
        }
      }
    }
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [paletteOpen, toggleTheme]);

  const modelLabel = (health && (health as unknown as { model?: string }).model) || 'agent';

  return (
    <div className="app-shell" data-theme={theme}>
      <Header title="MICRO-X AGENT" subtitle={modelLabel} />
      <div className="app-main">
        <SessionSidebar
          sessions={sessions}
          activeId={activeSessionId}
          onSelect={selectSession}
          onNew={newSession}
          hidden={!showSessions}
        />
        <div className="chat-region">
          <ChatLog
            messages={session.state.messages}
            banner={session.state.messages.length === 0 ? STARTUP_BANNER : undefined}
          />
          <PromptInput
            disabled={session.state.turnInFlight || !activeSessionId}
            placeholder={
              activeSessionId
                ? 'Type a message — Enter to send, Shift+Enter for newline'
                : 'Click "+ New" in the sidebar to start a session'
            }
            onSubmit={(text) => session.sendMessage(text)}
          />
        </div>
        <ToolPanel tools={session.state.tools} hidden={!showTools} />
      </div>
      <LogPanel lines={logLines} hidden={!showLogs} />
      <StatusBar
        status={session.status}
        model={modelLabel}
        sessionId={activeSessionId}
        turnInFlight={session.state.turnInFlight}
        usage={session.state.lastUsage}
      />
      <KeyHints />

      {session.state.pendingQuestion ? (
        <AskUserModal
          question={session.state.pendingQuestion}
          onAnswer={(ans) =>
            session.state.pendingQuestion &&
            session.answerQuestion(session.state.pendingQuestion.id, ans)
          }
          onCancel={() =>
            session.state.pendingQuestion &&
            session.answerQuestion(session.state.pendingQuestion.id, '')
          }
        />
      ) : null}

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onRunSlashCommand={runSlash}
        onToggleTasks={() => {
          /* TaskPanel not yet built; placeholder. */
        }}
        onSetTheme={setTheme}
      />

      {bootError ? (
        <div className="modal-backdrop" data-testid="boot-error" role="alert">
          <div className="modal">
            <h2>Server unreachable</h2>
            <div>{bootError}</div>
            <div className="modal-actions">
              <button onClick={() => setBootError(null)}>Dismiss</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
