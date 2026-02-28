import type { ChildProcess } from "node:child_process";

const MAX_EVENTS_PER_SESSION = 2000;

export interface SttEvent {
  seq: number;
  type: string;
  timestamp_utc: string;
  [key: string]: unknown;
}

export interface SttSession {
  session_id: string;
  repo: string;
  source: string;
  mic_device_id: string | null;
  mic_device_name: string | null;
  model: string;
  language: string;
  sample_rate: number;
  endpointing_ms: number;
  utterance_end_ms: number;
  diarize: boolean;
  chunk_seconds: number;
  created_utc: string;
  status: "running" | "stopped";
  next_seq: number;
  events: SttEvent[];
  stable_chunk_count: number;
  latest_transcript: string;
  error_count: number;
  process: ChildProcess | null;
  stopped: boolean;
}

const sessions = new Map<string, SttSession>();

export function utcNow(): string {
  return new Date().toISOString().replace(/\.\d+Z$/, "Z");
}

export function createSession(params: Omit<SttSession, "status" | "next_seq" | "events" | "stable_chunk_count" | "latest_transcript" | "error_count" | "process" | "stopped">): SttSession {
  const session: SttSession = {
    ...params,
    status: "running",
    next_seq: 1,
    events: [],
    stable_chunk_count: 0,
    latest_transcript: "",
    error_count: 0,
    process: null,
    stopped: false,
  };
  sessions.set(session.session_id, session);
  return session;
}

export function getSession(sessionId: string): SttSession | undefined {
  return sessions.get(sessionId);
}

export function pushEvent(session: SttSession, eventType: string, payload?: Record<string, unknown>): void {
  const event: SttEvent = {
    seq: session.next_seq,
    type: eventType,
    timestamp_utc: utcNow(),
    ...(payload ?? {}),
  };
  session.next_seq++;
  session.events.push(event);
  if (session.events.length > MAX_EVENTS_PER_SESSION) {
    session.events = session.events.slice(-MAX_EVENTS_PER_SESSION);
  }
}
