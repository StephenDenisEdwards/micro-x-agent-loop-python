from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class MemoryStore:
    def __init__(self, db_path: str):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._initialize_schema()

    def close(self) -> None:
        self._conn.close()

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        return self._conn.execute(query, params)

    def executemany(self, query: str, seq_of_params: list[tuple[Any, ...]]) -> sqlite3.Cursor:
        return self._conn.executemany(query, seq_of_params)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def _initialize_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                parent_session_id TEXT NULL REFERENCES sessions(id),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('active', 'archived', 'deleted')),
                model TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                seq INTEGER NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
                content_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                token_estimate INTEGER NOT NULL DEFAULT 0,
                UNIQUE(session_id, seq)
            );

            CREATE TABLE IF NOT EXISTS tool_calls (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                message_id TEXT NULL REFERENCES messages(id) ON DELETE SET NULL,
                tool_name TEXT NOT NULL,
                input_json TEXT NOT NULL,
                result_text TEXT NOT NULL,
                is_error INTEGER NOT NULL CHECK (is_error IN (0, 1)),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS checkpoints (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                user_message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                scope_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS checkpoint_files (
                checkpoint_id TEXT NOT NULL REFERENCES checkpoints(id) ON DELETE CASCADE,
                path TEXT NOT NULL,
                existed_before INTEGER NOT NULL CHECK (existed_before IN (0, 1)),
                backup_blob BLOB NULL,
                backup_path TEXT NULL,
                PRIMARY KEY (checkpoint_id, path),
                CHECK (
                    (backup_blob IS NOT NULL AND backup_path IS NULL)
                    OR (backup_blob IS NULL AND backup_path IS NOT NULL)
                    OR (backup_blob IS NULL AND backup_path IS NULL)
                )
            );

            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session_seq
                ON messages(session_id, seq);
            CREATE INDEX IF NOT EXISTS idx_messages_session_created
                ON messages(session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_tool_calls_session_created
                ON tool_calls(session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_checkpoints_session_created
                ON checkpoints(session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_events_session_created
                ON events(session_id, created_at);
            """
        )
        self._conn.commit()
