# Sessions and Rewind

## Overview

With `MemoryEnabled=true`, conversations are persisted to SQLite and assigned a stable session ID.

Default database path:

- `.micro_x/memory.db` (relative to current working directory)

## Startup Session Selection

Resolution order:

1. `ResumeSessionId` (must exist)
2. `ContinueConversation=true` + `SessionId` (load or create)
3. Create a new session
4. If `ForkSession=true`, fork the resolved session into a new active session

## Runtime Commands

- `/help` - show available local commands
- `/session` - show current active session ID
- `/session list [limit]` - list recent sessions (default 20)
- `/session name <title>` - rename the current session for easier identification
- `/session resume <id>` - switch to an existing session, reload persisted messages, and print a session summary
- `/session fork` - create a new forked session from current context
- `/rewind <checkpoint_id>` - restore tracked files from a checkpoint
- `/checkpoint list [limit]` - list recent checkpoints for the current session (default 20)
- `/checkpoint rewind <checkpoint_id>` - alias for rewinding a checkpoint

## Checkpoint Scope

When `EnableFileCheckpointing=true`, the agent captures file snapshots before tracked mutating tools run.

Current strict tracked tools:

- `write_file`
- `append_file`

Rewind reports per-file status:

- `restored`
- `removed`
- `skipped`
- `failed`

## How Checkpointing Works

Lifecycle for a user turn with tracked mutating tools:

1. User sends a message that results in one or more mutating tool calls.
2. Agent creates one checkpoint for that turn.
3. Before each tracked mutation, agent snapshots the file state (if a path is available).
4. Tool executes normally.
5. User can later run `/checkpoint list` to find checkpoint IDs and `/checkpoint rewind <id>` to restore.

What is saved:

- Checkpoint metadata: ID, created time, tool names, and a short prompt preview.
- Per-file snapshot metadata: path, whether file existed before, and backup bytes when applicable.

Failure semantics:

- Snapshot tracking failures do not block tool execution.
- If path tracking fails for a tool call, the tool still runs.
- Rewind is best effort and only affects files that were successfully tracked.

Typical workflow:

1. Do work that edits files (for example through `write_file` / `append_file`).
2. List checkpoints:
- `/checkpoint list`
3. Pick a checkpoint ID from the list and rewind:
- `/checkpoint rewind <checkpoint_id>`
4. Review per-file outcomes printed by the agent.
