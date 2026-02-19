# ADR-009: SQLite Memory for Sessions, Events, and File Checkpoints

## Status

Accepted

## Context

The agent originally operated as an in-memory REPL conversation with no durable session history and no built-in recovery from file mutations caused by tool calls.

As the workflow expanded, three capabilities became architectural requirements:

1. Persistent session continuity across process restarts
2. Auditable execution history (messages, tool calls, lifecycle events)
3. Rewind support for file mutations made by write tools

Options considered:

1. **No persistence** - keep transient in-memory history only
2. **Flat-file persistence** - JSON files per session/checkpoint
3. **SQLite persistence** - normalized local store with transactional writes and queryable history

## Decision

Adopt a local SQLite-backed memory subsystem for sessions and events, plus checkpoint-based file snapshot/rewind for mutating tools.

Reasons:

- **Transactional consistency.** SQLite provides atomic updates for session/message/tool/event records.
- **Queryable history.** Session resume, listing, summaries, and checkpoint browsing are simple SQL operations.
- **Operational simplicity.** Single local database file, no external service dependency.
- **Recovery support.** Checkpoints capture file state before mutation so `/rewind` can restore prior contents.

The implementation includes:

- `memory/store.py` schema bootstrap (`sessions`, `messages`, `tool_calls`, `checkpoints`, `checkpoint_files`, `events`)
- `memory/session_manager.py` for create/resume/fork/list/title and persisted message loading
- `memory/checkpoints.py` for checkpoint creation, file tracking, and rewind outcomes
- Runtime wiring in `__main__.py` and `agent.py` with session and checkpoint commands

## Consequences

**Easier:**

- Conversation continuity across runs with explicit session lifecycle control
- Traceability via persisted events and tool call records
- Safer autonomous editing through checkpoint+rewind support
- Deterministic pruning/retention policies over stored artifacts

**Harder:**

- Additional schema and migration/evolution responsibility
- Local storage growth management is now a first-class operational concern
- Checkpoint coverage remains bounded by what mutating tools are tracked
