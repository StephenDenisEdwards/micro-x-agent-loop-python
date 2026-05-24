import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { AgentWebSocketClient, type WsStatus } from '../api/websocket';
import { wsUrlForSession } from '../api/urls';
import {
  agentReducer,
  initialAgentState,
  __test as _agentTest,
} from '../state/agentStore';
import type { ChatMessage } from '../types/protocol';

export interface UseAgentSessionOptions {
  baseUrl: string;
  sessionId: string | null;
  /** Override the WebSocket factory — used by tests. */
  socketFactory?: ConstructorParameters<typeof AgentWebSocketClient>[0]['socketFactory'];
  /** Disable auto-reconnect (used by tests). */
  reconnect?: boolean;
}

export interface UseAgentSessionResult {
  state: ReturnType<typeof agentReducer>;
  status: WsStatus;
  sendMessage: (text: string) => void;
  answerQuestion: (id: string, text: string) => void;
  loadHistory: (messages: ChatMessage[]) => void;
  reset: () => void;
}

/**
 * Top-level hook that owns the WebSocket connection for a session and
 * exposes the resulting view-model.
 */
export function useAgentSession(opts: UseAgentSessionOptions): UseAgentSessionResult {
  const [state, dispatch] = useReducer(agentReducer, initialAgentState);
  const [status, setStatus] = useState<WsStatus>('idle');
  const clientRef = useRef<AgentWebSocketClient | null>(null);

  useEffect(() => {
    if (!opts.sessionId) return;
    const url = wsUrlForSession(opts.baseUrl, opts.sessionId);
    const client = new AgentWebSocketClient({
      url,
      socketFactory: opts.socketFactory,
      reconnect: opts.reconnect ?? true,
    });
    clientRef.current = client;
    const offFrame = client.onFrame((frame) => dispatch({ type: 'frame', frame }));
    const offStatus = client.onStatus((s) => setStatus(s));
    client.connect();
    return () => {
      offFrame();
      offStatus();
      client.disconnect();
      clientRef.current = null;
    };
  }, [opts.baseUrl, opts.sessionId, opts.socketFactory, opts.reconnect]);

  // Reset reducer when the session changes.
  useEffect(() => {
    dispatch({ type: 'reset' });
  }, [opts.sessionId]);

  const sendMessage = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    const id = _agentTest.nextMessageId();
    dispatch({ type: 'user-submit', id, text: trimmed });
    clientRef.current?.sendMessage(trimmed);
  }, []);

  const answerQuestion = useCallback((id: string, text: string) => {
    dispatch({ type: 'answer-question', id });
    clientRef.current?.sendAnswer(id, text);
  }, []);

  const loadHistory = useCallback((messages: ChatMessage[]) => {
    dispatch({ type: 'load-history', messages });
  }, []);

  const reset = useCallback(() => dispatch({ type: 'reset' }), []);

  return useMemo(
    () => ({ state, status, sendMessage, answerQuestion, loadHistory, reset }),
    [state, status, sendMessage, answerQuestion, loadHistory, reset],
  );
}
