import { describe, expect, it } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useAgentSession } from './useAgentSession';
import { createMockWsFactory } from '../test/mock-ws';

describe('useAgentSession', () => {
  it('connects when a session id is supplied and exposes status', async () => {
    const factory = createMockWsFactory(true);
    const { result } = renderHook(() =>
      useAgentSession({
        baseUrl: 'http://x',
        sessionId: 's1',
        socketFactory: factory,
        reconnect: false,
      }),
    );
    await waitFor(() => expect(factory.sockets.length).toBe(1));
    await waitFor(() => expect(result.current.status).toBe('open'));
  });

  it('sendMessage pushes a user message and emits a frame on the wire', async () => {
    const factory = createMockWsFactory(true);
    const { result } = renderHook(() =>
      useAgentSession({
        baseUrl: 'http://x',
        sessionId: 's1',
        socketFactory: factory,
        reconnect: false,
      }),
    );
    await waitFor(() => expect(result.current.status).toBe('open'));
    act(() => result.current.sendMessage('hello'));
    expect(result.current.state.messages.at(-1)).toMatchObject({ role: 'user', text: 'hello' });
    expect(result.current.state.turnInFlight).toBe(true);
    expect(factory.last()!.sent.at(-1)).toBe(JSON.stringify({ type: 'message', text: 'hello' }));
  });

  it('streams server frames into the reducer', async () => {
    const factory = createMockWsFactory(true);
    const { result } = renderHook(() =>
      useAgentSession({
        baseUrl: 'http://x',
        sessionId: 's1',
        socketFactory: factory,
        reconnect: false,
      }),
    );
    await waitFor(() => expect(result.current.status).toBe('open'));

    act(() => {
      factory.last()!.emitFrame({ type: 'text_delta', text: 'Hi' });
    });
    act(() => {
      factory.last()!.emitFrame({ type: 'text_delta', text: '!' });
    });
    act(() => {
      factory.last()!.emitFrame({ type: 'turn_complete', usage: {} });
    });
    const assistant = result.current.state.messages.find((m) => m.role === 'assistant');
    expect(assistant?.text).toBe('Hi!');
    expect(assistant?.pending).toBe(false);
    expect(result.current.state.turnInFlight).toBe(false);
  });

  it('answerQuestion clears the pending question and sends an answer frame', async () => {
    const factory = createMockWsFactory(true);
    const { result } = renderHook(() =>
      useAgentSession({
        baseUrl: 'http://x',
        sessionId: 's1',
        socketFactory: factory,
        reconnect: false,
      }),
    );
    await waitFor(() => expect(result.current.status).toBe('open'));
    act(() => {
      factory.last()!.emitFrame({ type: 'question', id: 'q1', text: 'why?', options: null });
    });
    expect(result.current.state.pendingQuestion?.id).toBe('q1');
    act(() => result.current.answerQuestion('q1', 'because'));
    expect(result.current.state.pendingQuestion).toBeNull();
    expect(factory.last()!.sent.at(-1)).toBe(
      JSON.stringify({ type: 'answer', question_id: 'q1', text: 'because' }),
    );
  });

  it('does not connect when sessionId is null', () => {
    const factory = createMockWsFactory(true);
    renderHook(() =>
      useAgentSession({
        baseUrl: 'http://x',
        sessionId: null,
        socketFactory: factory,
        reconnect: false,
      }),
    );
    expect(factory.sockets.length).toBe(0);
  });

  it('resets state when the session changes', async () => {
    const factory = createMockWsFactory(true);
    const { result, rerender } = renderHook(
      ({ id }: { id: string }) =>
        useAgentSession({ baseUrl: 'http://x', sessionId: id, socketFactory: factory, reconnect: false }),
      { initialProps: { id: 's1' } },
    );
    await waitFor(() => expect(result.current.status).toBe('open'));
    act(() => result.current.sendMessage('one'));
    expect(result.current.state.messages.length).toBeGreaterThan(0);
    rerender({ id: 's2' });
    expect(result.current.state.messages).toEqual([]);
  });
});
