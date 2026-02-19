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
