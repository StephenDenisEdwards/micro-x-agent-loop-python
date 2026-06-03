from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
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

    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        self._conn.execute("BEGIN")
        try:
            yield
        except Exception:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()

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
                created_at TEXT NOT NULL,
                was_truncated INTEGER NOT NULL DEFAULT 0 CHECK (was_truncated IN (0, 1)),
                original_chars INTEGER NULL
            );

            CREATE TABLE IF NOT EXISTS system_prompts (
                sha256 TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                chars INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cost_rollups (
                date TEXT NOT NULL,
                user_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                calls INTEGER NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                cost_usd REAL NOT NULL,
                PRIMARY KEY (date, user_id, task_type, provider, model)
            );

            CREATE TABLE IF NOT EXISTS eval_results (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                turn_number INTEGER NOT NULL,
                score REAL NOT NULL,
                rubric TEXT NOT NULL,
                rationale TEXT NOT NULL,
                judge_model TEXT NOT NULL,
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
            CREATE INDEX IF NOT EXISTS idx_events_session_type
                ON events(session_id, type);
            CREATE INDEX IF NOT EXISTS idx_eval_results_session
                ON eval_results(session_id, turn_number);
            CREATE INDEX IF NOT EXISTS idx_sessions_title_nocase
                ON sessions((json_extract(metadata_json, '$.title') COLLATE NOCASE));
            """
        )
        self._migrate_columns()
        self._conn.commit()

    def _migrate_columns(self) -> None:
        """Add columns introduced after a table's first release.

        ``CREATE TABLE IF NOT EXISTS`` never alters an existing table, so DBs
        created before a column existed need an explicit ``ALTER TABLE``. Each
        entry is idempotent — skipped when the column is already present.
        """
        migrations = {
            "tool_calls": {
                "was_truncated": "INTEGER NOT NULL DEFAULT 0",
                "original_chars": "INTEGER NULL",
            },
            "sessions": {
                "user_id": "TEXT NOT NULL DEFAULT ''",
            },
        }
        for table, columns in migrations.items():
            existing = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            for name, decl in columns.items():
                if name not in existing:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
