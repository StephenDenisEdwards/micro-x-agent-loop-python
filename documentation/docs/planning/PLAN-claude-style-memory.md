# Plan: Claude-Style Memory Features

## Goal

Add memory capabilities similar to Claude SDK while preserving the current local-agent architecture:

1. Session continuity (`session_id`, resume, continue, fork)
2. Persistent transcript/state storage
3. File checkpointing + rewind
4. Structured streaming state events
5. Retention and safety controls

This plan is incremental and intentionally starts with low-risk pieces.

## Current Baseline (Code Touchpoints)

- In-memory conversation only: `src/micro_x_agent_loop/agent.py`
- Runtime config bootstrapping: `src/micro_x_agent_loop/__main__.py`
- Agent config schema: `src/micro_x_agent_loop/agent_config.py`
- Tool execution pipeline: `src/micro_x_agent_loop/agent.py`
- Streaming output path: `src/micro_x_agent_loop/llm_client.py`
- File mutation tools: `src/micro_x_agent_loop/tools/write_file_tool.py`, `src/micro_x_agent_loop/tools/append_file_tool.py`, `src/micro_x_agent_loop/tools/bash_tool.py`

## Target Architecture

Add a `memory` package that owns persistent state and checkpoint metadata.

Proposed modules:

- `src/micro_x_agent_loop/memory/store.py`
- `src/micro_x_agent_loop/memory/models.py`
- `src/micro_x_agent_loop/memory/session_manager.py`
- `src/micro_x_agent_loop/memory/checkpoints.py`
- `src/micro_x_agent_loop/memory/events.py`
- `src/micro_x_agent_loop/memory/pruning.py`

Core rule: `Agent` is orchestration only; memory behavior lives behind `SessionManager` + `CheckpointManager`.

## Data Model (SQLite)

Use SQLite for portability and transactional safety.

Database file:

- Default: `.micro_x/memory.db` under current working directory
- Configurable via new config field `MemoryDbPath`

Tables:

1. `sessions`
- `id TEXT PRIMARY KEY` (session_id)
- `parent_session_id TEXT NULL`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`
- `status TEXT NOT NULL` (`active`, `archived`, `deleted`)
- `model TEXT NOT NULL`
- `metadata_json TEXT NOT NULL DEFAULT '{}'`

2. `messages`
- `id TEXT PRIMARY KEY` (uuid)
- `session_id TEXT NOT NULL`
- `seq INTEGER NOT NULL`
- `role TEXT NOT NULL` (`user`, `assistant`, `system`)
- `content_json TEXT NOT NULL`
- `created_at TEXT NOT NULL`
- `token_estimate INTEGER NOT NULL DEFAULT 0`
- Unique: `(session_id, seq)`

3. `tool_calls`
- `id TEXT PRIMARY KEY` (tool_use_id or generated UUID)
- `session_id TEXT NOT NULL`
- `message_id TEXT NULL` (assistant msg that emitted tool call)
- `tool_name TEXT NOT NULL`
- `input_json TEXT NOT NULL`
- `result_text TEXT NOT NULL`
- `is_error INTEGER NOT NULL` (0/1)
- `created_at TEXT NOT NULL`

4. `checkpoints`
- `id TEXT PRIMARY KEY` (checkpoint UUID)
- `session_id TEXT NOT NULL`
- `user_message_id TEXT NOT NULL`
- `created_at TEXT NOT NULL`
- `scope_json TEXT NOT NULL` (paths, mode, notes)

5. `checkpoint_files`
- `checkpoint_id TEXT NOT NULL`
- `path TEXT NOT NULL`
- `existed_before INTEGER NOT NULL` (0/1)
- `backup_blob BLOB NULL` (small files) or `backup_path TEXT NULL` (large)
- Primary key: `(checkpoint_id, path)`

6. `events`
- `id TEXT PRIMARY KEY`
- `session_id TEXT NOT NULL`
- `type TEXT NOT NULL`
- `payload_json TEXT NOT NULL`
- `created_at TEXT NOT NULL`

Indexes:

- `messages(session_id, seq)`
- `messages(session_id, created_at)`
- `tool_calls(session_id, created_at)`
- `checkpoints(session_id, created_at)`
- `events(session_id, created_at)`

## Config Additions

Add fields to `config.json` parsing and `AgentConfig`:

- `MemoryEnabled` (bool, default `false`)
- `MemoryDbPath` (string, default `.micro_x/memory.db`)
- `SessionId` (string, optional)
- `ContinueConversation` (bool, default `false`)
- `ResumeSessionId` (string, optional)
- `ForkSession` (bool, default `false`)
- `EnableFileCheckpointing` (bool, default `false`)
- `CheckpointWriteToolsOnly` (bool, default `true` in phase 2)
- `MemoryMaxSessions` (int, default `200`)
- `MemoryMaxMessagesPerSession` (int, default `5000`)
- `MemoryRetentionDays` (int, default `30`)

## API/Behavior Design

### Session Semantics

Resolution order at startup:

1. If `ResumeSessionId` provided, load it
2. If `ContinueConversation=true` and `SessionId` provided, load/create that ID
3. Else create new session
4. If `ForkSession=true`, clone transcript pointer into new `session_id` with `parent_session_id` set

### Message Persistence

- On each appended user/assistant message, write to `messages` table with monotonically increasing `seq`
- Keep in-memory `_messages` as working set, but derive initial state from store on startup/resume
- Compaction summary insertions are also persisted as normal messages

### Checkpoint Semantics

- Create checkpoint at each user turn when checkpointing is enabled
- Capture files before mutating tool executes
- `rewind_files(checkpoint_id)` restores all recorded paths for that checkpoint
- Rewind is best-effort only for tracked paths; report per-file outcome

## Tool Mutation Strategy

Track mutating tools explicitly:

- Phase 2 strict support: `write_file`, `append_file`
- Phase 3 best-effort support: `bash`
- Phase 3+ optional: MCP tools opt-in to "declares touched paths" contract

Implementation approach:

- Introduce `ToolExecutionContext` with fields:
  - `session_id`
  - `user_message_id`
  - `checkpoint_id`
- Wrap tool execution in `Agent._execute_tools` with pre/post hooks:
  - pre: detect target paths, snapshot if needed
  - post: record tool call/result metadata

## Structured Event Stream

Add an internal event emitter (`memory/events.py`) and emit:

- `session.started`
- `message.appended`
- `tool.started`
- `tool.completed`
- `checkpoint.created`
- `checkpoint.file_tracked`
- `rewind.started`
- `rewind.file_restored`
- `rewind.completed`

Start with logs + DB event rows. Later expose optional callback API.

## File-Level Change Plan

1. `src/micro_x_agent_loop/agent_config.py`
- Add memory/session/checkpoint config fields

2. `src/micro_x_agent_loop/__main__.py`
- Parse new config fields
- Build `SessionManager` and `CheckpointManager`
- Initialize agent with active session

3. `src/micro_x_agent_loop/agent.py`
- Load initial `_messages` from session manager on start
- Persist each message append
- Insert checkpoint hooks before mutating tools
- Add command handlers for local control commands:
  - `/session`
  - `/session resume <id>`
  - `/session fork`
  - `/rewind <checkpoint_id>`

4. `src/micro_x_agent_loop/tool.py`
- Optional protocol extension for mutation metadata:
  - `is_mutating: bool` (default false)
  - `predict_touched_paths(tool_input) -> list[str]` (optional)

5. `src/micro_x_agent_loop/tools/write_file_tool.py`
- Declare mutating metadata and touched path prediction

6. `src/micro_x_agent_loop/tools/append_file_tool.py`
- Declare mutating metadata and touched path prediction

7. `src/micro_x_agent_loop/tools/bash_tool.py`
- Phase 3: optional parser for common file-write command patterns; default untracked warning

8. `documentation/docs/operations/config.md`
- Document new memory/session/checkpoint settings

9. New docs:
- `documentation/docs/design/DESIGN-memory-system.md`
- `documentation/docs/operations/sessions.md`

## Rollout Phases

### Phase 1: Session Persistence (Low Risk)

Scope:

- SQLite store
- Session create/resume/fork
- Message persistence/reload
- No file rewind yet

Acceptance:

- Restart process and continue same session transcript
- Fork creates new session ID with visible ancestry

### Phase 2: Checkpoint/Rewind for File Tools (Medium Risk)

Scope:

- Checkpointing for `write_file` + `append_file`
- `rewind` command with per-file result report

Acceptance:

- Modify two files, rewind, both restored exactly
- New files created after checkpoint are removed on rewind

### Phase 3: Expanded Mutation Coverage + Events (High Risk)

Scope:

- Best-effort `bash` tracking
- Event persistence and callback plumbing
- Retention/pruning jobs

Acceptance:

- Event timeline reconstructs a full session
- Storage limits enforced without DB corruption

## Risk Register

1. Incorrect rewind restores wrong content or paths
- Mitigation: canonicalize paths, enforce working-directory boundaries, hash verification before/after restore

2. Incomplete tracking for `bash`/MCP side effects
- Mitigation: explicit "tracked vs untracked" status in checkpoint report; keep strict write-tool-only mode as default

3. Session store bloat/performance degradation
- Mitigation: retention policy + periodic pruning + max row guards + indexes

4. Concurrency race during parallel tool execution
- Mitigation: serialize checkpoint writes with async lock per session; atomic SQLite transactions

5. Secret leakage in persisted messages/tool outputs
- Mitigation: optional redaction filters before persistence, documented retention defaults

## Test Plan

Add tests under `tests/` (new folder expected):

1. Session tests
- create/resume/fork semantics
- message ordering and sequence monotonicity

2. Persistence tests
- reload transcript into in-memory `_messages`
- compaction + persistence interop

3. Checkpoint tests
- write and append round-trip rewind
- missing file and permission failure handling

4. Concurrency tests
- parallel tool calls with checkpoints under load

5. Pruning tests
- old sessions/messages purged according to retention

## Migration and Backward Compatibility

- Default `MemoryEnabled=false` keeps existing behavior unchanged
- When enabled with no prior DB, auto-create schema
- Existing compaction remains active; summaries become persisted messages

## Implementation Order (Concrete)

1. Add `memory/models.py` + schema migration bootstrap
2. Implement `SessionManager` create/resume/fork + message append/load
3. Wire session manager into `__main__.py` and `agent.py`
4. Add checkpoint manager for write/append tools
5. Add `/rewind` command path
6. Add docs and config references
7. Add tests for each phase before expanding scope

