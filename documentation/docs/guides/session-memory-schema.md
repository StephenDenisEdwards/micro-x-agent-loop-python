# Guide: Session Memory Schema Reference

SQLite schema for the memory system at `.micro_x/memory.db`.

## Overview

The memory system is opt-in (`MemoryEnabled=true`). When enabled, all conversation data, tool calls, checkpoints, and lifecycle events are persisted to a local SQLite database. The schema is bootstrapped automatically on first use.

Foreign keys are enforced (`PRAGMA foreign_keys = ON`). CASCADE deletes from `sessions` propagate to all child tables.

## Tables

### sessions

One row per conversation timeline.

```sql
CREATE TABLE sessions (
    id              TEXT PRIMARY KEY,
    parent_session_id TEXT NULL REFERENCES sessions(id),
    created_at      TEXT NOT NULL,          -- ISO 8601
    updated_at      TEXT NOT NULL,          -- Bumped on every append
    status          TEXT NOT NULL DEFAULT 'active',  -- active | archived | deleted
    model           TEXT,                   -- LLM model used
    metadata_json   TEXT DEFAULT '{}'       -- JSON object; stores "title" key
);

CREATE INDEX idx_sessions_title
    ON sessions(json_extract(metadata_json, '$.title') COLLATE NOCASE);
```

### messages

Ordered conversation transcript per session.

```sql
CREATE TABLE messages (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,       -- Monotonic per session
    role            TEXT NOT NULL,           -- user | assistant | system
    content_json    TEXT NOT NULL,           -- JSON string or content block array
    created_at      TEXT NOT NULL,
    token_estimate  INTEGER,                -- chars/4 heuristic
    UNIQUE(session_id, seq)
);

CREATE INDEX idx_messages_session_seq ON messages(session_id, seq);
CREATE INDEX idx_messages_session_time ON messages(session_id, created_at);
```

### tool_calls

Execution records for each tool invocation.

```sql
CREATE TABLE tool_calls (
    id              TEXT PRIMARY KEY,       -- tool_use_id or UUID
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    message_id      TEXT REFERENCES messages(id) ON DELETE SET NULL,
    tool_name       TEXT NOT NULL,
    input_json      TEXT,
    result_text     TEXT,
    is_error        INTEGER DEFAULT 0,      -- 0 or 1
    created_at      TEXT NOT NULL
);

CREATE INDEX idx_tool_calls_session_time ON tool_calls(session_id, created_at);
```

### checkpoints

Turn-level snapshot markers for file rewind.

```sql
CREATE TABLE checkpoints (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    user_message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    scope_json      TEXT                    -- {"tool_names": [...], "user_preview": "..."}
);

CREATE INDEX idx_checkpoints_session_time ON checkpoints(session_id, created_at);
```

### checkpoint_files

Per-file snapshots within a checkpoint.

```sql
CREATE TABLE checkpoint_files (
    checkpoint_id   TEXT NOT NULL REFERENCES checkpoints(id) ON DELETE CASCADE,
    path            TEXT NOT NULL,          -- Absolute resolved path
    existed_before  INTEGER NOT NULL,       -- 0 or 1
    backup_blob     BLOB,                   -- File bytes (small files)
    backup_path     TEXT,                   -- External path (large files, not yet used)
    PRIMARY KEY (checkpoint_id, path),
    CHECK ((backup_blob IS NULL) OR (backup_path IS NULL))
);
```

### events

Append-only lifecycle event log.

```sql
CREATE TABLE events (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    type            TEXT NOT NULL,          -- Event type string
    payload_json    TEXT,                   -- Structured JSON payload
    created_at      TEXT NOT NULL
);

CREATE INDEX idx_events_session_time ON events(session_id, created_at);
```

## Event Types

| Event Type | When | Payload Keys |
|------------|------|-------------|
| `session.started` | New session created | session_id, parent_session_id |
| `session.renamed` | Title changed | session_id, title |
| `message.appended` | Message persisted | session_id, message_id, seq, role |
| `tool.started` | Tool execution begins | tool_use_id, tool_name |
| `tool.completed` | Tool execution finishes | tool_use_id, tool_name, is_error |
| `checkpoint.created` | Checkpoint record inserted | session_id, checkpoint_id |
| `checkpoint.file_tracked` | File snapshot captured | checkpoint_id, path, existed_before |
| `checkpoint.file_untracked` | File tracking failed | checkpoint_id, tool_name, error |
| `rewind.started` | Rewind operation begins | checkpoint_id |
| `rewind.file_restored` | Per-file rewind result | checkpoint_id, path, status, detail |
| `rewind.completed` | Rewind operation finishes | checkpoint_id, results_count |

## Querying the Database

```bash
# Open the database
sqlite3 .micro_x/memory.db

# List sessions
SELECT id, status, json_extract(metadata_json, '$.title') as title,
       updated_at FROM sessions ORDER BY updated_at DESC;

# Message count per session
SELECT session_id, COUNT(*) as msg_count FROM messages GROUP BY session_id;

# Tool call history
SELECT tool_name, COUNT(*) as calls, SUM(is_error) as errors
FROM tool_calls GROUP BY tool_name ORDER BY calls DESC;

# Recent events
SELECT type, payload_json, created_at FROM events
ORDER BY created_at DESC LIMIT 20;

# Checkpoint files for a specific checkpoint
SELECT path, existed_before, LENGTH(backup_blob) as bytes
FROM checkpoint_files WHERE checkpoint_id = 'xxx';
```

## Pruning

Pruning runs once at startup and enforces three retention policies:

| Policy | Config Key | Default | Effect |
|--------|-----------|---------|--------|
| Time-based | `MemoryRetentionDays` | 30 | Delete sessions older than N days |
| Per-session cap | `MemoryMaxMessagesPerSession` | 200 | Keep only latest N messages per session |
| Global session cap | `MemoryMaxSessions` | 50 | Keep only most recent N sessions |

CASCADE deletes handle child rows automatically.

## Related

- [Memory System Design](../design/DESIGN-memory-system.md) — Full design document
- [ADR-009: SQLite Memory + File Checkpoints](../architecture/decisions/ADR-009-sqlite-memory-sessions-and-file-checkpoints.md)
- [Sessions and Rewind](../operations/sessions.md) — User-facing operations
- [Configuration Reference](../operations/config.md) — Memory config fields
