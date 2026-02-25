# Design: Memory System

## Overview

The memory system provides persistent session continuity, execution history, file checkpoint/rewind, and structured event tracing. It is implemented as an opt-in SQLite-backed subsystem that preserves the agent's conversational and operational state across process restarts.

When `MemoryEnabled=false` (the default), the agent behaves identically to its original in-memory-only mode. When enabled, every message, tool call, checkpoint, and lifecycle event is persisted locally.

## Package Structure

All memory code lives in `src/micro_x_agent_loop/memory/`:

| Module | Responsibility |
|--------|---------------|
| `store.py` | SQLite connection, schema bootstrap, transaction context manager |
| `models.py` | Frozen dataclasses for `SessionRecord` and `MessageRecord` |
| `session_manager.py` | Session CRUD, message persistence, fork, tool call recording, summaries |
| `checkpoints.py` | File snapshotting before mutations, rewind with per-file outcomes |
| `events.py` | Synchronous event emission (INSERT per event) |
| `event_sink.py` | Async batched event emission (queue + periodic flush) |
| `pruning.py` | Time-based and count-based retention enforcement |

## Data Model

Database file: `.micro_x/memory.db` (configurable via `MemoryDbPath`).

### Tables

**`sessions`** — one row per conversation timeline.

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | UUID or explicit ID |
| `parent_session_id` | TEXT NULL FK | Set when forked |
| `created_at` | TEXT | ISO 8601 |
| `updated_at` | TEXT | Bumped on every message/tool append |
| `status` | TEXT | `active`, `archived`, or `deleted` |
| `model` | TEXT | LLM model used |
| `metadata_json` | TEXT | JSON object; stores `title` key |

**`messages`** — ordered conversation transcript.

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | UUID |
| `session_id` | TEXT FK CASCADE | |
| `seq` | INTEGER | Monotonic per session, UNIQUE(session_id, seq) |
| `role` | TEXT | `user`, `assistant`, or `system` |
| `content_json` | TEXT | JSON string or content block array |
| `created_at` | TEXT | |
| `token_estimate` | INTEGER | chars/4 heuristic at write time |

**`tool_calls`** — execution records for each tool invocation.

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | tool_use_id or UUID |
| `session_id` | TEXT FK CASCADE | |
| `message_id` | TEXT FK SET NULL | Assistant message that triggered the call |
| `tool_name` | TEXT | |
| `input_json` | TEXT | |
| `result_text` | TEXT | |
| `is_error` | INTEGER | 0 or 1 |
| `created_at` | TEXT | |

**`checkpoints`** — turn-level snapshot markers.

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | UUID |
| `session_id` | TEXT FK CASCADE | |
| `user_message_id` | TEXT FK CASCADE | The user message that triggered this turn |
| `created_at` | TEXT | |
| `scope_json` | TEXT | `{"tool_names": [...], "user_preview": "..."}` |

**`checkpoint_files`** — per-file snapshots within a checkpoint.

| Column | Type | Notes |
|--------|------|-------|
| `checkpoint_id` | TEXT FK CASCADE | Composite PK with path |
| `path` | TEXT | Absolute resolved path |
| `existed_before` | INTEGER | 0 or 1 |
| `backup_blob` | BLOB NULL | File bytes (for small files) |
| `backup_path` | TEXT NULL | External backup path (for large files, not yet used) |

CHECK constraint ensures at most one of `backup_blob` / `backup_path` is set.

**`events`** — append-only lifecycle event log.

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | UUID |
| `session_id` | TEXT FK CASCADE | |
| `type` | TEXT | Event type string |
| `payload_json` | TEXT | Structured JSON payload |
| `created_at` | TEXT | |

### Indexes

- `messages(session_id, seq)` and `messages(session_id, created_at)`
- `tool_calls(session_id, created_at)`
- `checkpoints(session_id, created_at)`
- `events(session_id, created_at)`
- `sessions(json_extract(metadata_json, '$.title') COLLATE NOCASE)` — for title-based resolution

Foreign keys are enforced via `PRAGMA foreign_keys = ON`. CASCADE deletes from sessions propagate to all child tables.

## Component Interactions

### Bootstrap Wiring

`bootstrap.py` builds the memory stack when `MemoryEnabled=true`:

1. Create `MemoryStore` (opens/creates SQLite database, bootstraps schema)
2. Create `AsyncEventSink` and start its background flush task
3. Create `EventEmitter` backed by the sink
4. Create `SessionManager` and `CheckpointManager` with the store and emitter
5. Resolve the active session (resume, continue, create, or fork)
6. Run `prune_memory()` once at startup
7. Pass all components into `AgentConfig` and construct the `Agent`

On shutdown (`__main__.py` finally block): close event sink, close memory store.

### Agent Integration

`Agent` receives the memory components via `AgentConfig` and uses them through callbacks wired into `TurnEngine`:

- **`_append_message()`** — writes to both in-memory `_messages` and `session_manager.append_message()`
- **`_ensure_checkpoint_for_turn()`** — creates one checkpoint per user turn when tool_use blocks are present
- **`_maybe_track_mutation()`** — snapshots files before mutating tools execute; failures are non-blocking
- **`_record_tool_call()`** — persists tool invocation records
- **`_emit_tool_started()` / `_emit_tool_completed()`** — emits lifecycle events
- **`initialize_session()`** — loads persisted messages into `_messages` on startup/resume

### Session Resolution

At startup, the session is resolved in this order:

1. `ResumeSessionId` — must exist (by ID or case-insensitive title match)
2. `ContinueConversation=true` + `SessionId` — load or create
3. Otherwise — create a new session
4. If `ForkSession=true` — fork the resolved session

Runtime commands (`/session resume`, `/session new`, `/session fork`) can switch the active session during a conversation.

## Checkpoint Lifecycle

### Creation

One checkpoint is created per user turn, the first time tool_use blocks are detected:

1. `_ensure_checkpoint_for_turn()` checks: memory enabled, checkpoint manager enabled, active session exists, no checkpoint yet for this turn
2. Creates a checkpoint record with scope metadata (tool names, user message preview)
3. Sets `_current_checkpoint_id` to prevent duplicate checkpoints in the same turn

### File Tracking

Before each mutating tool executes:

1. `_maybe_track_mutation()` checks: is the tool in `_MUTATING_TOOL_NAMES` or does it have `is_mutating=True`?
2. If `write_tools_only=True` (default), only `write_file` and `append_file` are tracked
3. `checkpoint_manager.maybe_track_tool_input()` resolves the path, enforces working directory boundaries, reads current bytes, and stores as `backup_blob`
4. If tracking fails (e.g., path outside working directory), a warning is logged and a `checkpoint.file_untracked` event is emitted — the tool still executes normally

### Rewind

When the user runs `/rewind <checkpoint_id>`:

1. Load all `checkpoint_files` for that checkpoint
2. For each file:
   - If `existed_before=True` and backup exists: restore bytes
   - If `existed_before=False` and file now exists: delete it
   - Otherwise: skip
3. Report per-file outcome: `restored`, `removed`, `skipped`, or `failed`

## Event Taxonomy

Events are emitted at key lifecycle points and persisted to the `events` table:

| Event Type | When | Payload |
|------------|------|---------|
| `session.started` | New session created | session_id, parent_session_id |
| `session.renamed` | Title changed | session_id, title |
| `message.appended` | Message persisted | session_id, message_id, seq, role |
| `tool.started` | Tool execution begins | tool_use_id, tool_name |
| `tool.completed` | Tool execution finishes | tool_use_id, tool_name, is_error |
| `checkpoint.created` | Checkpoint record inserted | session_id, checkpoint_id |
| `checkpoint.file_tracked` | File snapshot captured | checkpoint_id, path, existed_before |
| `checkpoint.file_untracked` | File tracking failed (non-blocking) | checkpoint_id, tool_name, error |
| `rewind.started` | Rewind operation begins | checkpoint_id |
| `rewind.file_restored` | Per-file rewind result | checkpoint_id, path, status, detail |
| `rewind.completed` | Rewind operation finishes | checkpoint_id, results_count |

### Emission Paths

Two emission strategies are available:

1. **Synchronous** (`EventEmitter` without sink) — direct INSERT + commit per event. Simple but blocks the caller.
2. **Async batched** (`EventEmitter` with `AsyncEventSink`) — events are queued via `put_nowait()` and flushed in batches (default: 50 events or every 0.5 seconds). Graceful drain on close. This is the default in production bootstrap.

## Pruning

`prune_memory()` enforces retention policies. It runs once at startup in `bootstrap_runtime()`.

Three pruning dimensions:

1. **Time-based** — delete sessions with `updated_at` older than `MemoryRetentionDays`
2. **Per-session message cap** — for each remaining session, keep only the latest `MemoryMaxMessagesPerSession` messages by `seq`
3. **Global session cap** — keep only the most recent `MemoryMaxSessions` sessions by `updated_at`

Cascade deletes handle child rows (messages, tool_calls, checkpoints, checkpoint_files, events) automatically.

## Mutation Tracking Scope

Currently tracked mutating tools:

| Tool | Tracking | How |
|------|----------|-----|
| `write_file` | Strict | `is_mutating=True`, `predict_touched_paths()` returns `[path]` |
| `append_file` | Strict | `is_mutating=True`, `predict_touched_paths()` returns `[path]` |
| `bash` | Not tracked | No mutation metadata (Phase 3 planned) |
| MCP tools | Not tracked | No mutation protocol support (future) |

The `_MUTATING_TOOL_NAMES` set in `Agent` provides a hardcoded fallback. Tools can also declare `is_mutating=True` via the `Tool` Protocol for dynamic detection.

## Related Documentation

- [ADR-009](../architecture/decisions/ADR-009-sqlite-memory-sessions-and-file-checkpoints.md) — architectural decision for SQLite memory
- [Sessions and Rewind](../operations/sessions.md) — user-facing operations guide
- [Configuration Reference](../operations/config.md) — memory config fields
- [Tool System Design](DESIGN-tool-system.md) — Tool Protocol including mutation metadata
- [PLAN-claude-style-memory](../planning/PLAN-claude-style-memory.md) — full plan with phases and remaining work
