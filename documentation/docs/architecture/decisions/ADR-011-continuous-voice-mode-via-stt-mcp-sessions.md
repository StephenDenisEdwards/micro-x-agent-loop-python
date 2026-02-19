# ADR-011: Continuous Voice Mode via STT MCP Sessions

## Status

Accepted

## Context

The agent originally accepted only typed REPL input. A one-shot STT path (`ia_transcribe_once`) was added, but it required explicit per-call invocation and did not support continuous hands-free interaction.

The requirement is continuous speech-driven usage where utterances are transcribed and fed into normal agent turns without manual typing.

Key constraints:

- The existing MCP integration is request/response tool invocation.
- The core agent loop must remain stable and provider/tool agnostic.
- We already have reusable Deepgram transcription components in `interview-assist-2`.

Options considered:

1. Keep one-shot STT only
2. Add custom bidirectional streaming transport between agent and STT service
3. Add session-based STT MCP tools with polling and finalized-utterance events

## Decision

Adopt option 3: session-based STT over MCP with polling.

Implementation shape:

- STT MCP server exposes session lifecycle tools:
  - `stt_start_session`
  - `stt_get_updates`
  - `stt_get_session`
  - `stt_stop_session`
  - `stt_list_devices`
- Agent adds local voice controls:
  - `/voice start [microphone|loopback]`
  - `/voice status`
  - `/voice stop`
- Agent runs background polling/queue consumers and injects `utterance_final` text into the normal `run()` path.
- REPL input is executed via `asyncio.to_thread(input, ...)` so the event loop remains live while voice polling runs.

## Consequences

**Easier:**

- Continuous hands-free interaction without changing the core turn execution model
- Reuse of existing Deepgram/audio stack via MCP boundary
- Incremental rollout: session scaffolding first, then segmentation/quality tuning

**Harder:**

- Polling introduces eventual consistency and tuning tradeoffs (poll interval vs latency)
- Additional runtime concurrency (poll task + queue consumer + turn lock)
- Voice quality depends on segmentation and environment noise; requires iterative tuning
