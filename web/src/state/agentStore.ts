import type {
  ChatMessage,
  PendingQuestion,
  ServerFrame,
  ToolEntry,
} from '../types/protocol';

export interface AgentState {
  messages: ChatMessage[];
  tools: ToolEntry[];
  /** Currently streaming assistant message id, if any. */
  streamingId: string | null;
  pendingQuestion: PendingQuestion | null;
  /** Most recent ``usage`` payload from a ``turn_complete``. */
  lastUsage: Record<string, unknown> | null;
  /** True while an agent turn is in flight (between user submit and turn_complete). */
  turnInFlight: boolean;
}

export const initialAgentState: AgentState = {
  messages: [],
  tools: [],
  streamingId: null,
  pendingQuestion: null,
  lastUsage: null,
  turnInFlight: false,
};

export type AgentAction =
  | { type: 'frame'; frame: ServerFrame }
  | { type: 'user-submit'; id: string; text: string }
  | { type: 'answer-question'; id: string }
  | { type: 'load-history'; messages: ChatMessage[] }
  | { type: 'reset' };

let _idCounter = 0;
function nextMessageId(): string {
  _idCounter += 1;
  return `m-${Date.now().toString(36)}-${_idCounter}`;
}

export function agentReducer(state: AgentState, action: AgentAction): AgentState {
  switch (action.type) {
    case 'reset':
      return initialAgentState;

    case 'load-history':
      return {
        ...initialAgentState,
        messages: action.messages,
      };

    case 'user-submit':
      return {
        ...state,
        turnInFlight: true,
        streamingId: null,
        messages: [
          ...state.messages,
          { id: action.id, role: 'user', text: action.text },
        ],
      };

    case 'answer-question':
      if (state.pendingQuestion?.id !== action.id) return state;
      return { ...state, pendingQuestion: null };

    case 'frame':
      return applyFrame(state, action.frame);

    default:
      return state;
  }
}

function applyFrame(state: AgentState, frame: ServerFrame): AgentState {
  switch (frame.type) {
    case 'text_delta':
      return appendDelta(state, frame.text);

    case 'tool_started': {
      const entry: ToolEntry = {
        toolUseId: frame.tool_use_id,
        name: frame.tool,
        status: 'running',
        input: frame.tool_input ?? null,
        startedAt: Date.now(),
      };
      return { ...state, tools: [...state.tools, entry] };
    }

    case 'tool_completed': {
      const tools = state.tools.map((t) =>
        t.toolUseId === frame.tool_use_id
          ? {
              ...t,
              status: frame.error ? ('error' as const) : ('ok' as const),
              durationMs: frame.duration_ms,
              resultChars: frame.result_chars,
              wasSummarized: frame.was_summarized,
              wasTruncated: frame.was_truncated,
            }
          : t,
      );
      // If the tool wasn't seen via tool_started (rare), append it as a
      // completed entry so the user sees something.
      if (!tools.some((t) => t.toolUseId === frame.tool_use_id)) {
        tools.push({
          toolUseId: frame.tool_use_id,
          name: frame.tool,
          status: frame.error ? 'error' : 'ok',
          startedAt: Date.now(),
          durationMs: frame.duration_ms,
          resultChars: frame.result_chars,
          wasSummarized: frame.was_summarized,
          wasTruncated: frame.was_truncated,
        });
      }
      return { ...state, tools };
    }

    case 'turn_complete':
      return finalizeStream({
        ...state,
        turnInFlight: false,
        lastUsage: frame.usage,
      });

    case 'error':
      return finalizeStream({
        ...state,
        turnInFlight: false,
        messages: [
          ...state.messages,
          { id: nextMessageId(), role: 'error', text: frame.message },
        ],
      });

    case 'system_message':
      // Suppress empty system messages — the TUI uses them as spacers.
      if (!frame.text.trim()) return state;
      return {
        ...state,
        messages: [
          ...state.messages,
          { id: nextMessageId(), role: 'system', text: frame.text },
        ],
      };

    case 'question':
      return {
        ...state,
        pendingQuestion: { id: frame.id, text: frame.text, options: frame.options },
      };

    case 'pong':
      return state;

    default: {
      // exhaustive — the type assertion documents that all cases are handled.
      void (frame satisfies never);
      return state;
    }
  }
}

function appendDelta(state: AgentState, text: string): AgentState {
  if (state.streamingId) {
    const messages = state.messages.map((m) =>
      m.id === state.streamingId ? { ...m, text: m.text + text } : m,
    );
    return { ...state, messages };
  }
  const id = nextMessageId();
  return {
    ...state,
    streamingId: id,
    messages: [...state.messages, { id, role: 'assistant', text, pending: true }],
  };
}

function finalizeStream(state: AgentState): AgentState {
  if (!state.streamingId) return state;
  const messages = state.messages.map((m) =>
    m.id === state.streamingId ? { ...m, pending: false } : m,
  );
  return { ...state, messages, streamingId: null };
}

// Exported for tests — lets us reset the id counter between cases.
export const __test = {
  resetIdCounter(): void {
    _idCounter = 0;
  },
  nextMessageId,
};
