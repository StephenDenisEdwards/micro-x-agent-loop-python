import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from './App';
import { RestClient } from './api/rest';
import { createMockWsFactory } from './test/mock-ws';
import type { HealthInfo, SessionSummary, ChatMessage } from './types/protocol';

function makeFakeRest(overrides: Partial<{
  health: HealthInfo;
  sessions: SessionSummary[];
  messages: ChatMessage[];
  createId: string;
}> = {}): RestClient {
  const health = overrides.health ?? {
    status: 'ok',
    active_sessions: 0,
    tools: 1,
    memory_enabled: true,
  };
  const sessions = overrides.sessions ?? [{ id: 'demo', title: 'Demo' }];
  const messages = overrides.messages ?? [];
  const createId = overrides.createId ?? 'new-session-id';
  return {
    health: vi.fn().mockResolvedValue(health),
    listSessions: vi.fn().mockResolvedValue(sessions),
    getMessages: vi.fn().mockResolvedValue(messages),
    createSession: vi.fn().mockResolvedValue(createId),
    deleteSession: vi.fn().mockResolvedValue(undefined),
  } as unknown as RestClient;
}

describe('App', () => {
  it('boots, fetches health and sessions, and renders the chat shell', async () => {
    const rest = makeFakeRest();
    const factory = createMockWsFactory(true);
    render(<App restClient={rest} socketFactory={factory} baseUrl="http://x" />);
    await waitFor(() => expect(screen.getByTestId('session-sidebar')).toBeInTheDocument());
    expect(screen.getByTestId('app-header')).toHaveTextContent('MICRO-X AGENT');
    expect(screen.getByTestId('chat-log')).toBeInTheDocument();
    expect(screen.getByTestId('status-bar')).toBeInTheDocument();
  });

  it('clicking + New creates a session via REST and selects it', async () => {
    const rest = makeFakeRest({ createId: 'created-1' });
    const factory = createMockWsFactory(true);
    render(<App restClient={rest} socketFactory={factory} baseUrl="http://x" />);
    await waitFor(() => expect(screen.getByTestId('session-sidebar')).toBeInTheDocument());
    await userEvent.click(screen.getByTestId('new-session-button'));
    await waitFor(() => expect(rest.createSession).toHaveBeenCalled());
    await waitFor(() => {
      const items = screen.getAllByTestId('session-item');
      expect(items.some((el) => el.dataset.sessionId === 'created-1')).toBe(true);
    });
  });

  it('sends a typed message over the WebSocket', async () => {
    const rest = makeFakeRest();
    const factory = createMockWsFactory(true);
    render(<App restClient={rest} socketFactory={factory} baseUrl="http://x" />);
    await waitFor(() => expect(factory.sockets.length).toBeGreaterThan(0));
    // wait for the first socket to be open
    await waitFor(() => expect(factory.last()!.readyState).toBe(1));
    await userEvent.type(screen.getByTestId('prompt-input'), 'hi there{Enter}');
    await waitFor(() => {
      expect(factory.last()!.sent.some((f) => f.includes('"hi there"'))).toBe(true);
    });
    expect(screen.getByText('hi there')).toBeInTheDocument();
  });

  it('streams text_delta frames into an assistant bubble', async () => {
    const rest = makeFakeRest();
    const factory = createMockWsFactory(true);
    render(<App restClient={rest} socketFactory={factory} baseUrl="http://x" />);
    await waitFor(() => expect(factory.last()?.readyState).toBe(1));
    await act(async () => {
      factory.last()!.emitFrame({ type: 'text_delta', text: 'Hello ' });
      factory.last()!.emitFrame({ type: 'text_delta', text: 'world' });
      factory.last()!.emitFrame({ type: 'turn_complete', usage: {} });
    });
    expect(screen.getByText(/Hello world/)).toBeInTheDocument();
  });

  it('opens the command palette on Ctrl+P and runs a slash command', async () => {
    const rest = makeFakeRest();
    const factory = createMockWsFactory(true);
    render(<App restClient={rest} socketFactory={factory} baseUrl="http://x" />);
    await waitFor(() => expect(factory.last()?.readyState).toBe(1));
    await userEvent.keyboard('{Control>}p{/Control}');
    expect(screen.getByTestId('command-palette')).toBeInTheDocument();
    await userEvent.type(screen.getByTestId('command-palette-input'), '/help');
    await userEvent.keyboard('{Enter}');
    await waitFor(() => {
      expect(factory.last()!.sent.some((f) => f.includes('"/help"'))).toBe(true);
    });
  });

  it('shows the AskUserModal on a question frame and answers it', async () => {
    const rest = makeFakeRest();
    const factory = createMockWsFactory(true);
    render(<App restClient={rest} socketFactory={factory} baseUrl="http://x" />);
    await waitFor(() => expect(factory.last()?.readyState).toBe(1));
    await act(async () => {
      factory.last()!.emitFrame({
        type: 'question',
        id: 'q1',
        text: 'Proceed?',
        options: null,
      });
    });
    expect(screen.getByTestId('ask-user-modal')).toBeInTheDocument();
    await userEvent.type(screen.getByTestId('ask-user-input'), 'yes{Enter}');
    await waitFor(() => {
      expect(factory.last()!.sent.some((f) => f.includes('"answer"'))).toBe(true);
    });
    expect(screen.queryByTestId('ask-user-modal')).toBeNull();
  });

  it('Ctrl+S toggles the session sidebar', async () => {
    const rest = makeFakeRest();
    const factory = createMockWsFactory(true);
    render(<App restClient={rest} socketFactory={factory} baseUrl="http://x" />);
    await waitFor(() => expect(screen.getByTestId('session-sidebar')).toBeInTheDocument());
    expect(screen.getByTestId('session-sidebar')).not.toHaveClass('hidden');
    await userEvent.keyboard('{Control>}s{/Control}');
    expect(screen.getByTestId('session-sidebar')).toHaveClass('hidden');
  });

  it('Ctrl+T toggles the tool panel', async () => {
    const rest = makeFakeRest();
    const factory = createMockWsFactory(true);
    render(<App restClient={rest} socketFactory={factory} baseUrl="http://x" />);
    await waitFor(() => expect(screen.getByTestId('tool-panel')).toBeInTheDocument());
    expect(screen.getByTestId('tool-panel')).not.toHaveClass('hidden');
    await userEvent.keyboard('{Control>}t{/Control}');
    expect(screen.getByTestId('tool-panel')).toHaveClass('hidden');
  });

  it('renders an error frame in the chat log', async () => {
    const rest = makeFakeRest();
    const factory = createMockWsFactory(true);
    render(<App restClient={rest} socketFactory={factory} baseUrl="http://x" />);
    await waitFor(() => expect(factory.last()?.readyState).toBe(1));
    await act(async () => {
      factory.last()!.emitFrame({ type: 'error', message: 'something broke' });
    });
    expect(screen.getByText('something broke')).toBeInTheDocument();
    expect(screen.getByText('something broke')).toHaveClass('error');
  });

  it('shows the boot error overlay when /api/health fails', async () => {
    const failingRest = {
      health: vi.fn().mockRejectedValue(new Error('connection refused')),
      listSessions: vi.fn().mockResolvedValue([]),
      getMessages: vi.fn().mockResolvedValue([]),
      createSession: vi.fn(),
      deleteSession: vi.fn(),
    } as unknown as RestClient;
    const factory = createMockWsFactory(true);
    render(<App restClient={failingRest} socketFactory={factory} baseUrl="http://x" />);
    await waitFor(() => expect(screen.getByTestId('boot-error')).toBeInTheDocument());
    expect(screen.getByTestId('boot-error')).toHaveTextContent('connection refused');
  });
});
