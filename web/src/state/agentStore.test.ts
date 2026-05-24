import { beforeEach, describe, expect, it } from 'vitest';
import {
  agentReducer,
  initialAgentState,
  __test,
  type AgentAction,
  type AgentState,
} from './agentStore';
import type { ServerFrame } from '../types/protocol';

function frame(f: ServerFrame): AgentAction {
  return { type: 'frame', frame: f };
}

beforeEach(() => {
  __test.resetIdCounter();
});

describe('agentReducer', () => {
  it('starts with the initial state', () => {
    expect(initialAgentState.messages).toEqual([]);
    expect(initialAgentState.tools).toEqual([]);
    expect(initialAgentState.streamingId).toBeNull();
    expect(initialAgentState.pendingQuestion).toBeNull();
    expect(initialAgentState.turnInFlight).toBe(false);
  });

  it('appends the user message and sets turnInFlight on user-submit', () => {
    const next = agentReducer(initialAgentState, {
      type: 'user-submit',
      id: 'u1',
      text: 'hello',
    });
    expect(next.messages).toEqual([{ id: 'u1', role: 'user', text: 'hello' }]);
    expect(next.turnInFlight).toBe(true);
  });

  it('streams assistant text deltas into a single pending message', () => {
    let state: AgentState = initialAgentState;
    state = agentReducer(state, { type: 'user-submit', id: 'u1', text: 'hi' });
    state = agentReducer(state, frame({ type: 'text_delta', text: 'Hel' }));
    state = agentReducer(state, frame({ type: 'text_delta', text: 'lo!' }));
    const assistantMsgs = state.messages.filter((m) => m.role === 'assistant');
    expect(assistantMsgs).toHaveLength(1);
    expect(assistantMsgs[0]!.text).toBe('Hello!');
    expect(assistantMsgs[0]!.pending).toBe(true);
    expect(state.streamingId).toBe(assistantMsgs[0]!.id);
  });

  it('finalises the streaming message on turn_complete', () => {
    let state: AgentState = initialAgentState;
    state = agentReducer(state, { type: 'user-submit', id: 'u1', text: 'hi' });
    state = agentReducer(state, frame({ type: 'text_delta', text: 'ok' }));
    state = agentReducer(state, frame({ type: 'turn_complete', usage: { input_tokens: 1, output_tokens: 2 } }));
    const assistantMsgs = state.messages.filter((m) => m.role === 'assistant');
    expect(assistantMsgs[0]!.pending).toBe(false);
    expect(state.streamingId).toBeNull();
    expect(state.turnInFlight).toBe(false);
    expect(state.lastUsage).toEqual({ input_tokens: 1, output_tokens: 2 });
  });

  it('records running tools and updates them on completion', () => {
    let state: AgentState = initialAgentState;
    state = agentReducer(state, frame({
      type: 'tool_started',
      tool_use_id: 't1',
      tool: 'filesystem__read_file',
      tool_input: { path: '/a.txt' },
    }));
    expect(state.tools).toHaveLength(1);
    expect(state.tools[0]!.status).toBe('running');
    expect(state.tools[0]!.input).toEqual({ path: '/a.txt' });

    state = agentReducer(state, frame({
      type: 'tool_completed',
      tool_use_id: 't1',
      tool: 'filesystem__read_file',
      error: false,
      result_chars: 128,
      was_summarized: false,
      was_truncated: false,
      duration_ms: 42,
    }));
    expect(state.tools[0]!.status).toBe('ok');
    expect(state.tools[0]!.durationMs).toBe(42);
    expect(state.tools[0]!.resultChars).toBe(128);
  });

  it('marks tools as error when tool_completed has error=true', () => {
    let state: AgentState = initialAgentState;
    state = agentReducer(state, frame({ type: 'tool_started', tool_use_id: 't1', tool: 'bash' }));
    state = agentReducer(state, frame({
      type: 'tool_completed',
      tool_use_id: 't1',
      tool: 'bash',
      error: true,
      result_chars: 0,
      was_summarized: false,
      was_truncated: false,
      duration_ms: 5,
    }));
    expect(state.tools[0]!.status).toBe('error');
  });

  it('synthesises a completed entry when tool_started was never seen', () => {
    const state = agentReducer(initialAgentState, frame({
      type: 'tool_completed',
      tool_use_id: 'orphan',
      tool: 'ghost',
      error: false,
      result_chars: 0,
      was_summarized: false,
      was_truncated: false,
      duration_ms: 0,
    }));
    expect(state.tools).toHaveLength(1);
    expect(state.tools[0]!.name).toBe('ghost');
    expect(state.tools[0]!.status).toBe('ok');
  });

  it('captures questions and clears them on answer-question', () => {
    let state: AgentState = initialAgentState;
    state = agentReducer(state, frame({
      type: 'question',
      id: 'q1',
      text: 'Continue?',
      options: [{ value: 'y', label: 'Yes' }, { value: 'n', label: 'No' }],
    }));
    expect(state.pendingQuestion?.id).toBe('q1');
    state = agentReducer(state, { type: 'answer-question', id: 'q1' });
    expect(state.pendingQuestion).toBeNull();
  });

  it('ignores answer-question for stale question ids', () => {
    const state = agentReducer(initialAgentState, { type: 'answer-question', id: 'nope' });
    expect(state.pendingQuestion).toBeNull();
  });

  it('appends error frames as error messages and ends the turn', () => {
    let state: AgentState = initialAgentState;
    state = agentReducer(state, { type: 'user-submit', id: 'u1', text: 'hi' });
    state = agentReducer(state, frame({ type: 'error', message: 'boom' }));
    expect(state.messages.at(-1)!.role).toBe('error');
    expect(state.messages.at(-1)!.text).toBe('boom');
    expect(state.turnInFlight).toBe(false);
  });

  it('suppresses empty system_message frames (TUI spacers)', () => {
    const state = agentReducer(initialAgentState, frame({ type: 'system_message', text: '   ' }));
    expect(state.messages).toEqual([]);
  });

  it('appends non-empty system_message frames', () => {
    const state = agentReducer(initialAgentState, frame({ type: 'system_message', text: 'hello' }));
    expect(state.messages).toHaveLength(1);
    expect(state.messages[0]!.role).toBe('system');
  });

  it('ignores pong frames', () => {
    const state = agentReducer(initialAgentState, frame({ type: 'pong' }));
    expect(state).toBe(initialAgentState);
  });

  it('reset returns to the initial state', () => {
    let state: AgentState = initialAgentState;
    state = agentReducer(state, { type: 'user-submit', id: 'u1', text: 'hi' });
    state = agentReducer(state, { type: 'reset' });
    expect(state).toEqual(initialAgentState);
  });

  it('load-history replaces the messages list', () => {
    const state = agentReducer(initialAgentState, {
      type: 'load-history',
      messages: [{ id: 'h1', role: 'user', text: 'old' }],
    });
    expect(state.messages).toEqual([{ id: 'h1', role: 'user', text: 'old' }]);
  });
});
