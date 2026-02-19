# Plan: OpenClaw-Inspired Memory Features

## Goal

Add memory capabilities inspired by OpenClaw memory/session workflows while preserving the current local-agent architecture:

1. Session continuity (`session_id`, resume, continue, fork)
2. Persistent transcript/state storage
3. File checkpointing + rewind
4. Structured streaming state events
5. Retention and safety controls

This plan is incremental and intentionally starts with low-risk pieces.

## Status (Updated February 19, 2026)

Current implementation status:

- Phase 1 (Session persistence): Completed.
- Phase 2 (Checkpoint/rewind for `write_file`/`append_file`): Completed.
- Phase 3 (expanded mutation coverage + advanced events/callbacks): In progress.

Delivered in code:

- SQLite-backed memory store and schema bootstrap.
- Session create/resume/fork and persisted message reload.
- Persisted tool call records.
- Checkpoint + rewind for `write_file` and `append_file`.
- Local commands: `/help`, `/session`, `/session list [limit]`, `/session resume <id>`, `/session fork`, `/rewind <checkpoint_id>`.
- Startup/session config wiring and startup pruning.
- Initial automated tests for session, checkpoint, rewind, pruning, and non-blocking checkpoint tracking failures.

Remaining from plan:

- Best-effort `bash` and broader mutation tracking.
- Optional external event callback API.
- Additional stress/concurrency tests and deeper retention policy hardening.

## Source Inspiration and Scope

Primary inspiration:

- OpenClaw memory/session/checkpoint workflow patterns (resume, branching, recoverability, and event visibility).

Scope clarification:

- This plan adapts those patterns to this repo's local architecture.
- It does not attempt to replicate proprietary hosted backend internals from any vendor.

## Detailed Feature Intent + Implementation Comparison

This section clarifies what "OpenClaw-inspired memory" means in this repo.

Important scope note:

- The goal is practical workflow parity (resume, fork, rewind, event traceability), not implementation parity with external platforms.
- Where external behavior is unspecified, this plan chooses explicit, deterministic local behavior.

Quick comparison:

| Capability | OpenClaw-Inspired Expectation | Planned Here | Why Different |
| --- | --- | --- | --- |
| Session continuity | Resume and branch prior conversations | Explicit `session_id` create/resume/continue/fork with deterministic precedence | Local/offline operation and predictable testable semantics |
| Transcript persistence | Conversation state survives beyond one run | SQLite-backed `sessions/messages/tool_calls` with ordered replay | Inspectable local storage and transactional safety |
| Rewind | Recover from undesired agent changes | First-class checkpoint + per-file rewind reporting | Local file mutation risk is primary; explicit undo is required |
| Streaming state events | Meaningful runtime state transitions | Typed local events persisted to DB, callback-ready later | Repo-specific observability and offline replay/debugging |
| Retention and safety | Controlled memory lifecycle | Configurable caps/retention, planned redaction hooks | Operator-controlled local compliance and storage bounds |

### Comparison: Claude Code Memory Features (Current)

Based on Anthropic's Claude Code memory docs (retrieved February 19, 2026), Claude Code memory is primarily instruction memory via `CLAUDE.md` files and related commands (`/memory`, `/init`, `#` shortcut), with hierarchical file loading and imports.

What Claude Code memory emphasizes:

- File-based instruction memory in multiple scopes (enterprise, project, user).
- Hierarchical loading and precedence of memory files.
- Importing additional files from memory files (`@path` syntax).
- Fast authoring/editing workflow for memory files via CLI shortcuts and commands.

How this plan overlaps:

- Both approaches aim to preserve useful context across sessions.
- Both make memory operator-editable, not opaque.
- Both support project-level conventions and reusable workflow guidance.

How this plan differs:

- This plan adds persisted conversational state (`sessions/messages/tool_calls`) rather than only instruction files.
- This plan includes checkpoint/rewind of file mutations, which is outside Claude Code memory-file scope.
- This plan includes structured persisted runtime events for replay/debugging.
- This plan proposes retention/pruning over persisted execution artifacts, not just memory-file maintenance.

Why both can coexist conceptually:

- Claude Code-style memory files are strong for stable instructions ("how to work").
- Session/checkpoint/event memory is strong for execution history ("what happened").
- Combining both yields policy + history + recoverability for local autonomous coding workflows.

### 1) Session continuity (`session_id`, resume, continue, fork)

What we are planning:

- Every conversation is assigned a stable `session_id`.
- Users can explicitly resume an existing session.
- Users can continue a named session across process restarts.
- Users can fork a session to branch from prior context without mutating the original lineage.

What it does exactly:

- `session_id` identifies a single conversation timeline.
- `resume` reopens an existing timeline and loads its persisted messages as active context.
- `continue` with a known ID reuses that timeline across process restarts without requiring transcript copy/paste.
- `fork` creates a new timeline that starts from the same prior transcript, then diverges independently.
- `parent_session_id` preserves ancestry so operators can trace where a branch came from.
- Session status (`active`, `archived`, `deleted`) controls lifecycle without physically deleting everything immediately.

Use cases:

- Ongoing research thread: continue a multi-day analysis session without re-briefing the assistant each day.
- Policy drafting alternatives: fork one branch for "strict policy" and another for "balanced policy" and compare.
- Customer support escalation: resume the exact prior troubleshooting context for a returning case.
- Operations handoff: day shift forks a night-shift session to test a different remediation path safely.

Why this matters:

- Enables long-running work over days/weeks.
- Makes experimentation safer (fork before risky changes).
- Supports repeatable debugging by replaying the same conversation state.

How this compares to OpenClaw-inspired behavior:

- Similar: supports continuing prior context and branching/fork-like workflows.
- Different: this repo defines explicit startup precedence and deterministic local IDs rather than relying on opaque server-side session routing.

Why this difference is intentional:

- Local agent architecture must work offline and be inspectable.
- Deterministic semantics reduce operator confusion and make tests straightforward.

### 2) Persistent transcript/state storage

What we are planning:

- Persist user/assistant/system messages and tool call outcomes in SQLite.
- Rehydrate in-memory conversation from persisted rows at startup/resume.
- Keep sequence ordering explicit with monotonic per-session `seq`.

What it does exactly:

- Each message append writes a row to `messages` with `session_id`, `seq`, role, payload, and timestamp.
- Tool invocations and outputs are persisted in `tool_calls`, including error state.
- On startup/resume, the session manager reconstructs `_messages` from stored rows in `seq` order.
- Compaction outputs (summaries) are persisted as first-class messages, not hidden side state.
- The persisted state becomes the source of truth; in-memory state is a runtime cache/working set.

Use cases:

- Crash recovery: restart after process failure and continue the same conversation in any domain.
- Audit trail: inspect what prompt/response/tool sequence produced a compliance or quality issue.
- Knowledge continuity: preserve institutional context across operator changes and long-running cases.
- Quality review: compare two sessions to understand why one produced better outputs than another.

Why this matters:

- Process restarts no longer lose context.
- Auditability: operators can inspect exactly what context the model saw.
- Better incident response when prompts/tool outputs need post-mortem analysis.

How this compares to OpenClaw-inspired behavior:

- Similar: conversation state survives beyond a single in-memory run.
- Different: this implementation is local-first with a portable SQLite schema and queryable tables.

Why this difference is intentional:

- Local, file-backed state matches this project's "run from current working directory" model.
- SQLite gives transactional safety without introducing service dependencies.

### 3) File checkpointing + rewind

What we are planning:

- Create checkpoints around mutating tool execution.
- Track pre-change file state and restore via `rewind_files(checkpoint_id)`.
- Start strict with `write_file`/`append_file`; expand carefully for `bash` and MCP later.

What it does exactly:

- At user-turn boundaries (when enabled), create a checkpoint record tied to session and triggering message.
- Before a tracked mutating tool runs, snapshot pre-change file state for predicted touched paths.
- For each tracked file, record whether it existed beforehand and store backup content (blob or backup file path).
- `rewind_files(checkpoint_id)` replays backups:
- Existing-before files are restored to their exact prior bytes.
- Files created after checkpoint are removed if they did not previously exist.
- Restore results are reported per file (restored, removed, skipped, failed) for operator visibility.
- Rewind scope is intentionally limited to tracked paths, avoiding false certainty about untracked side effects.

Use cases:

- Document rollback: revert accidental changes to runbooks, reports, or SOP documents.
- Data prep safety: undo unintended edits to local CSV/JSON artifacts used in analysis workflows.
- Sandbox operations: run high-risk automated transformations, then rewind to known baseline.
- Incident recovery: restore a critical subset first, then investigate remaining untracked side effects.

Why this matters:

- Converts risky tool-based edits into reversible operations.
- Reduces fear of autonomous edits in real repositories.
- Provides a concrete "undo" primitive for local agent workflows.

How this compares to OpenClaw-inspired behavior:

- Similar: user can recover from undesired agent edits by reverting to earlier state.
- Different: this plan makes file rewind a first-class, explicit local primitive with per-file restoration reporting.

Why this difference is intentional:

- In local development environments, source-tree mutation is the highest-risk action.
- Explicit checkpoint metadata is required for trust, diagnostics, and safe automation.

### 4) Structured streaming state events

What we are planning:

- Emit typed lifecycle events for session/message/tool/checkpoint/rewind milestones.
- Persist events in DB first; optional callbacks can be layered later.

What it does exactly:

- Emit normalized event records for milestones like `session.started`, `message.appended`, `tool.started`, `tool.completed`, and rewind lifecycle events.
- Attach typed payloads (`payload_json`) with IDs/timestamps needed to correlate messages, tools, and checkpoints.
- Persist events in append-only style so execution order is reconstructable after the fact.
- Keep event emission internal-first (logs + DB) before exposing a public callback surface.
- Enable downstream consumers to build timelines without parsing unstructured console text.

Use cases:

- Timeline reconstruction: answer "what happened just before this wrong output?" in support or analytics flows.
- UI/ops visibility: render activity timelines for supervisors reviewing autonomous runs.
- Monitoring/alerts: detect repeated tool failures, retries, or unusual rewind patterns.
- Post-incident review: reconstruct end-to-end execution behavior for operational learning.

Why this matters:

- Improves observability beyond plain console logs.
- Enables UI timelines, replay tooling, and external monitoring integrations.
- Supports deterministic debugging of "what happened when".

How this compares to OpenClaw-inspired behavior:

- Similar: exposes a stream of meaningful state transitions during execution.
- Different: event taxonomy and payloads are explicitly defined for this codebase and persisted locally.

Why this difference is intentional:

- This repo needs events that map directly to its own tool and file mutation lifecycle.
- Persisted events enable offline debugging and compliance-friendly traceability.

### 5) Retention and safety controls

What we are planning:

- Configurable caps for sessions/messages plus time-based retention.
- Planned optional redaction filters before persistence.
- Explicit defaults that preserve current behavior unless memory is enabled.

What it does exactly:

- Enforce configurable limits (`MemoryMaxSessions`, `MemoryMaxMessagesPerSession`) to prevent unbounded growth.
- Apply time-based pruning (`MemoryRetentionDays`) for stale sessions/messages/events.
- Keep memory opt-in (`MemoryEnabled=false` by default) so existing deployments do not change behavior silently.
- Provide planned redaction hooks to scrub sensitive substrings before writing messages/tool outputs to disk.
- Run pruning in controlled, transactional operations to avoid partial deletion corruption.

Use cases:

- Compliance hygiene: enforce finite retention windows for sensitive customer or internal content.
- Cost/resource control: keep local storage growth stable for long-running assistant usage.
- Shared environment safety: reduce accidental long-term retention of credentials or personal data.
- Policy by environment: strict retention for regulated operations, longer retention for research workflows.

Why this matters:

- Prevents unbounded local data growth.
- Reduces risk of retaining secrets longer than intended.
- Keeps the feature safe-by-default for existing users.

How this compares to OpenClaw-inspired behavior:

- Similar: memory is governed by lifecycle controls, not infinite retention.
- Different: retention is controlled with local config knobs and local pruning jobs.

Why this difference is intentional:

- Local deployments vary widely in risk tolerance and storage constraints.
- Operators need direct control instead of service-level defaults.

## Non-Goals and Deliberate Deviations

Non-goals in this plan:

- Reproducing any proprietary, undocumented hosted backend implementation details.
- Adding cloud service dependencies for memory in phase 1/2.
- Attempting complete side-effect tracking for arbitrary shell/MCP behavior in early phases.

Deliberate deviations:

- Local-first storage (SQLite) instead of hosted session state.
- Explicit checkpoint/rewind contracts for file tools.
- Deterministic startup/session resolution rules.
- Repo-specific event schema optimized for engineering observability.

These deviations are intentional because this project optimizes for local control, inspectability, reversibility, and incremental safety.

## Example End-to-End Flow

This example shows one concrete user turn from prompt to rewind.

Scenario:

- Session already exists: `session_id = sess_A1`
- Checkpointing enabled for `write_file` and `append_file`
- User asks the agent to update `src/app.py` and append notes to `CHANGELOG.md`

Step-by-step lifecycle:

1. User message received
- Runtime appends user content to in-memory `_messages`.
- Session manager persists message row:
- `messages(session_id=sess_A1, seq=42, role=user, content_json=..., created_at=...)`
- Event emitted/persisted: `message.appended`.

2. Model response + tool calls generated
- Assistant emits tool uses: `write_file(src/app.py)` and `append_file(CHANGELOG.md)`.
- Assistant message persisted:
- `messages(session_id=sess_A1, seq=43, role=assistant, content_json=..., created_at=...)`
- Event emitted/persisted: `tool.started` (per tool as execution begins).

3. Checkpoint created for this turn
- Checkpoint manager creates:
- `checkpoints(id=cp_9001, session_id=sess_A1, user_message_id=<msg-42>, scope_json=...)`
- Event emitted/persisted: `checkpoint.created`.

4. Pre-mutation snapshots captured
- Before `write_file(src/app.py)`, system records prior bytes of `src/app.py`.
- Before `append_file(CHANGELOG.md)`, system records prior bytes of `CHANGELOG.md`.
- Rows inserted into `checkpoint_files` for each path with `existed_before` and backup storage reference.
- Event emitted/persisted: `checkpoint.file_tracked` for each path.

5. Tools execute and results persist
- `write_file` executes and returns success/failure text.
- `append_file` executes and returns success/failure text.
- `tool_calls` rows persisted with input/result/error flags.
- Tool result blocks are appended as user-role tool_result content and persisted as message seq 44.
- Event emitted/persisted: `tool.completed` for each tool.

6. Process crash and restart (optional branch)
- If process stops now, on restart with resume:
- Session manager loads messages by `seq` (42,43,44,...) and restores active context.
- No manual transcript reconstruction required.

7. Operator decides to undo changes
- User issues `/rewind cp_9001`.
- Event emitted/persisted: `rewind.started`.
- Rewind manager iterates `checkpoint_files` for `cp_9001`:
- Restores prior bytes for files that existed before checkpoint.
- Deletes files that did not exist before checkpoint but were created during the turn.
- Emits per-file events: `rewind.file_restored` with outcome.
- Emits final event: `rewind.completed`.

8. Rewind report returned to user
- Console/report lists each tracked path and status:
- `src/app.py: restored`
- `CHANGELOG.md: restored`
- Any failures shown explicitly with error text.

What this demonstrates:

- Memory continuity: context survives restart.
- Reversibility: mutating tool effects can be rolled back deterministically.
- Observability: event + table records reconstruct exactly what happened.

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

## Related Plan

Gateway/server migration is tracked separately in:

- `documentation/docs/planning/PLAN-openclaw-like-gateway-architecture.md`

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
