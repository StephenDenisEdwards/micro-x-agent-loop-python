"""SQLite persistence for broker jobs and run history."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class BrokerStore:
    """Manages broker_jobs and broker_runs tables in a SQLite database."""

    def __init__(self, db_path: str) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS broker_jobs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                trigger_type TEXT NOT NULL DEFAULT 'cron',
                cron_expr TEXT,
                timezone TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                prompt_template TEXT NOT NULL,
                session_id TEXT,
                config_profile TEXT,
                response_channel TEXT NOT NULL DEFAULT 'log',
                response_target TEXT,
                overlap_policy TEXT NOT NULL DEFAULT 'skip_if_running',
                timeout_seconds INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_run_at TEXT,
                next_run_at TEXT
            );

            CREATE TABLE IF NOT EXISTS broker_runs (
                id TEXT PRIMARY KEY,
                job_id TEXT,
                trigger_source TEXT NOT NULL,
                prompt TEXT NOT NULL,
                session_id TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                started_at TEXT,
                completed_at TEXT,
                result_summary TEXT,
                error_text TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_broker_jobs_enabled_next
                ON broker_jobs(enabled, next_run_at);
            CREATE INDEX IF NOT EXISTS idx_broker_runs_job_id
                ON broker_runs(job_id, started_at);
            CREATE INDEX IF NOT EXISTS idx_broker_runs_status
                ON broker_runs(status, started_at);
        """)

    # -- Job CRUD --

    def create_job(
        self,
        *,
        name: str,
        cron_expr: str,
        prompt_template: str,
        timezone: str = "UTC",
        session_id: str | None = None,
        config_profile: str | None = None,
        overlap_policy: str = "skip_if_running",
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        now = _now_iso()
        self._conn.execute(
            """INSERT INTO broker_jobs
               (id, name, trigger_type, cron_expr, timezone, enabled,
                prompt_template, session_id, config_profile,
                response_channel, overlap_policy, timeout_seconds,
                created_at, updated_at)
               VALUES (?, ?, 'cron', ?, ?, 1, ?, ?, ?, 'log', ?, ?, ?, ?)""",
            (job_id, name, cron_expr, timezone, prompt_template,
             session_id, config_profile, overlap_policy, timeout_seconds,
             now, now),
        )
        self._conn.commit()
        return self.get_job(job_id)  # type: ignore[return-value]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM broker_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_jobs(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        if enabled_only:
            rows = self._conn.execute(
                "SELECT * FROM broker_jobs WHERE enabled = 1 ORDER BY name"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM broker_jobs ORDER BY name"
            ).fetchall()
        return [dict(r) for r in rows]

    def update_job(self, job_id: str, **fields: Any) -> None:
        allowed = {
            "name", "cron_expr", "timezone", "enabled", "prompt_template",
            "session_id", "config_profile", "overlap_policy", "timeout_seconds",
            "last_run_at", "next_run_at",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = _now_iso()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [job_id]
        self._conn.execute(
            f"UPDATE broker_jobs SET {set_clause} WHERE id = ?", values
        )
        self._conn.commit()

    def delete_job(self, job_id: str) -> bool:
        cursor = self._conn.execute("DELETE FROM broker_jobs WHERE id = ?", (job_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    # -- Run tracking --

    def create_run(
        self,
        *,
        job_id: str | None,
        trigger_source: str,
        prompt: str,
        session_id: str | None = None,
    ) -> str:
        run_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO broker_runs
               (id, job_id, trigger_source, prompt, session_id, status, started_at)
               VALUES (?, ?, ?, ?, ?, 'running', ?)""",
            (run_id, job_id, trigger_source, prompt, session_id, _now_iso()),
        )
        self._conn.commit()
        return run_id

    def complete_run(self, run_id: str, *, result_summary: str | None = None) -> None:
        self._conn.execute(
            """UPDATE broker_runs
               SET status = 'completed', completed_at = ?, result_summary = ?
               WHERE id = ?""",
            (_now_iso(), result_summary, run_id),
        )
        self._conn.commit()

    def fail_run(self, run_id: str, *, error_text: str) -> None:
        self._conn.execute(
            """UPDATE broker_runs
               SET status = 'failed', completed_at = ?, error_text = ?
               WHERE id = ?""",
            (_now_iso(), error_text, run_id),
        )
        self._conn.commit()

    def skip_run(self, run_id: str) -> None:
        self._conn.execute(
            """UPDATE broker_runs
               SET status = 'skipped', completed_at = ?
               WHERE id = ?""",
            (_now_iso(), run_id),
        )
        self._conn.commit()

    def has_running_run(self, job_id: str) -> bool:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM broker_runs WHERE job_id = ? AND status = 'running'",
            (job_id,),
        ).fetchone()
        return row[0] > 0

    def list_runs(self, job_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if job_id:
            rows = self._conn.execute(
                "SELECT * FROM broker_runs WHERE job_id = ? ORDER BY started_at DESC LIMIT ?",
                (job_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM broker_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._conn.close()
