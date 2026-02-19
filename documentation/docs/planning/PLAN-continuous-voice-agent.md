# Plan: Continuous Voice Agent via STT MCP Sessions

**Status: In progress** (Updated 2026-02-19)

Implementation snapshot:

- Phase 1: Completed
- Phase 2: Completed
- Phase 3: Completed (baseline)
- Phase 4: In progress

Latest implementation note:

- STT sessions now use a persistent Deepgram streaming process in `interview-assist-2`.
- Agent still consumes session events via `stt_get_updates` polling (hybrid architecture).

## Goal

Enable continuous microphone-driven interaction with the Python agent, where spoken utterances are transcribed and fed into normal agent turns without manual typing.

## Problem Statement

Current state:

- `interview-assist__ia_transcribe_once` provides one-shot capture/transcribe.
- The agent loop (`src/micro_x_agent_loop/agent.py`) is turn-based text REPL.
- There is no session-based speech stream integrated into agent turn execution.

Desired state:

- User starts voice mode once.
- Speech is segmented into utterances continuously.
- Finalized utterances are injected as user turns automatically.
- Agent responses continue through existing tool/model pipeline.

## Architectural Decision

Use **session-based STT MCP tools** with polling and finalized-utterance events.

Why:

- Fits existing MCP request/response tool model.
- Avoids introducing custom bidirectional transport into the Python agent.
- Reuses `interview-assist-2` audio + Deepgram implementation.
- Keeps voice logic isolated in STT service boundary.

## Scope

In scope:

- Session-based STT lifecycle API
- Continuous utterance capture and retrieval
- Agent voice mode command(s) and background poll loop
- Turn-queueing and concurrency guardrails

Out of scope (initially):

- Full duplex speech synthesis (TTS)
- Wake-word support
- Multi-user or remote microphone routing

## Repo Responsibilities

`C:\Users\steph\source\repos\interview-assist-2`:

- Implement persistent STT session runtime and utterance queue.
- Provide machine-friendly command/tool surface for session lifecycle and polling.

`C:\Users\steph\source\repos\micro-x-agent-loop-python`:

- Add voice mode orchestration to agent runtime.
- Poll STT updates and enqueue finalized utterances as normal user turns.
- Add UX commands and logs.

## Target Tool Contract (MCP)

Required tools:

- `stt_list_devices()`
- `stt_start_session(source, mode, model, language, vad/silence config) -> {session_id}`
- `stt_get_updates(session_id, since_seq, limit) -> {events, next_seq}`
- `stt_stop_session(session_id) -> {status}`
- `stt_get_session(session_id) -> {status, counters, latest_transcript}`

Event schema (minimum):

- `seq` (monotonic integer)
- `type` (`utterance_final`, `warning`, `error`, `info`)
- `text` (for utterance events)
- `timestamp_utc`
- `offset_ms`
- `confidence` (optional)
- `speaker` (optional)

## Execution Plan

### Phase 1: STT Session Runtime (interview-assist-2)

Status: Completed

1. Add an in-memory `SttSessionManager` with:
   - session map
   - cancellation tokens
   - bounded event queue per session
2. Wire Deepgram/audio capture into session workers.
3. Emit finalized utterance events from stable text callbacks.
4. Implement session cleanup and idle timeout.
5. Add unit tests for sequence/order, queue boundaries, and shutdown.

Deliverable:

- Session runtime that can run continuously for a single process lifetime.

### Phase 2: MCP Surface for Sessions

Status: Completed

1. Expose lifecycle/update tools above.
2. Validate and sanitize input options.
3. Guarantee deterministic error payloads.
4. Add integration tests for start/get_updates/stop behavior.

Deliverable:

- Stable MCP API for continuous transcription polling.

### Phase 3: Python Agent Voice Mode

Status: Completed (baseline)

1. Add local commands:
   - `/voice start`
   - `/voice stop`
   - `/voice status`
2. Start background poll task after `/voice start`.
3. For each `utterance_final`:
   - enqueue text
   - process sequentially through existing `Agent.run` flow
4. Prevent overlap:
   - if agent currently processing, queue utterance
   - configurable queue size and overflow policy
5. Add visible logs for:
   - queued utterance
   - dropped utterance
   - tool/model turn boundaries

Deliverable:

- End-to-end hands-free voice-to-agent interaction.

### Phase 4: Hardening

Status: In progress

1. Debounce/merge very short utterances.
2. Noise suppression thresholds and min-duration filters.
3. Recovery logic on MCP session crash (auto-restart policy).
4. Optional confidence gating before enqueuing a turn.

Deliverable:

- Production-grade stability for daily use.

## Concurrency Rules

- Single active voice session per agent process (initially).
- One active LLM turn at a time.
- Utterances buffered in FIFO queue.
- Session polling independent from turn execution.

## Acceptance Criteria

Functional:

- User can start voice mode once and speak multiple prompts without typing.
- Each finalized utterance triggers exactly one agent turn.
- Voice mode can be stopped cleanly with no orphan tasks.

Reliability:

- No deadlocks under rapid utterance bursts.
- Graceful handling of Deepgram/MCP disconnects.
- Bounded memory growth for long sessions.

Latency:

- Median speech-end to agent-turn-start under 1.5 seconds on local network.

## Risks and Mitigations

- False segmentation in noisy environments:
  - expose silence/VAD tuning in `stt_start_session`.
- Turn flooding from rapid utterances:
  - queue limits + collapse policy.
- MCP process restart drops session state:
  - explicit status events + auto-recreate option in Phase 4.

## Rollout Strategy

1. Ship Phase 1+2 behind MCP tools only.
2. Test manually via MCP tool calls.
3. Enable `/voice` commands in Python agent.
4. Collect logs/metrics and tune thresholds.

## Immediate Next Tasks

1. Add latency and queue-depth metrics/log summaries for voice sessions.
2. Tune segmentation/short-utterance filtering and confidence gating defaults.
3. Add stronger recovery policy for MCP/STT session interruption and auto-recreate behavior.
4. Design MCP push/subscription path for STT events (keep `stt_get_updates` as fallback).
