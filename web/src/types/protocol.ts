// Server -> client WebSocket frames, mirroring src/micro_x_agent_loop/server/ws_channel.py

export interface TextDeltaFrame {
  type: 'text_delta';
  text: string;
}

export interface ToolStartedFrame {
  type: 'tool_started';
  tool_use_id: string;
  tool: string;
  tool_input?: Record<string, unknown> | null;
}

export interface ToolCompletedFrame {
  type: 'tool_completed';
  tool_use_id: string;
  tool: string;
  error: boolean;
  result_chars: number;
  was_summarized: boolean;
  was_truncated: boolean;
  duration_ms: number;
}

export interface TurnCompleteFrame {
  type: 'turn_complete';
  usage: Record<string, unknown>;
}

export interface ErrorFrame {
  type: 'error';
  message: string;
}

export interface SystemMessageFrame {
  type: 'system_message';
  text: string;
}

export interface QuestionFrame {
  type: 'question';
  id: string;
  text: string;
  options: { value: string; label?: string }[] | null;
}

export interface PongFrame {
  type: 'pong';
}

export type ServerFrame =
  | TextDeltaFrame
  | ToolStartedFrame
  | ToolCompletedFrame
  | TurnCompleteFrame
  | ErrorFrame
  | SystemMessageFrame
  | QuestionFrame
  | PongFrame;

// Client -> server frames.

export interface UserMessageFrame {
  type: 'message';
  text: string;
}

export interface AnswerFrame {
  type: 'answer';
  question_id: string;
  text: string;
}

export interface PingFrame {
  type: 'ping';
}

export type ClientFrame = UserMessageFrame | AnswerFrame | PingFrame;

// Higher level view models used by the React UI.

export interface SessionSummary {
  id: string;
  title?: string | null;
  created_at?: string | null;
  message_count?: number | null;
  model?: string | null;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'error';
  text: string;
  pending?: boolean;
}

export type ToolStatus = 'running' | 'ok' | 'error';

export interface ToolEntry {
  toolUseId: string;
  name: string;
  status: ToolStatus;
  input?: Record<string, unknown> | null;
  startedAt: number;
  durationMs?: number;
  resultChars?: number;
  wasSummarized?: boolean;
  wasTruncated?: boolean;
}

export interface PendingQuestion {
  id: string;
  text: string;
  options: { value: string; label?: string }[] | null;
}

export interface HealthInfo {
  status: string;
  active_sessions: number;
  tools: number;
  memory_enabled: boolean;
  broker?: {
    enabled: boolean;
    jobs_total: number;
    jobs_enabled: number;
    active_runs: number;
    channels: string[];
  };
}
