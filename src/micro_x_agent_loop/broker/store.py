"""SQLite persistence for broker jobs and run history."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
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
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
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
                job_id TEXT REFERENCES broker_jobs(id) ON DELETE CASCADE,
                trigger_source TEXT NOT NULL,
                prompt TEXT NOT NULL,
                session_id TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                started_at TEXT,
                completed_at TEXT,
                result_summary TEXT,
                error_text TEXT,
                response_channel TEXT,
                response_target TEXT,
                response_sent INTEGER NOT NULL DEFAULT 0,
                response_error TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_broker_jobs_enabled_next
                ON broker_jobs(enabled, next_run_at);
            CREATE INDEX IF NOT EXISTS idx_broker_runs_job_id
                ON broker_runs(job_id, started_at);
            CREATE INDEX IF NOT EXISTS idx_broker_runs_status
                ON broker_runs(status, started_at);

            CREATE TABLE IF NOT EXISTS broker_questions (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES broker_runs(id) ON DELETE CASCADE,
                question_text TEXT NOT NULL,
                options TEXT,
                answer TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                asked_at TEXT NOT NULL,
                answered_at TEXT,
                timeout_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_broker_questions_run_status
                ON broker_questions(run_id, status);
        """)

        # Migration: add response columns for existing databases created before Phase 2
        for col, col_type, default in [
            ("response_channel", "TEXT", None),
            ("response_target", "TEXT", None),
            ("response_sent", "INTEGER NOT NULL", "0"),
            ("response_error", "TEXT", None),
        ]:
            try:
                default_clause = f" DEFAULT {default}" if default else ""
                self._conn.execute(f"ALTER TABLE broker_runs ADD COLUMN {col} {col_type}{default_clause}")
            except sqlite3.OperationalError:
                pass  # Column already exists

        # Migration: add HITL and retry columns to broker_jobs
        for col, col_type, default in [
            ("hitl_enabled", "INTEGER NOT NULL", "0"),
            ("hitl_timeout_seconds", "INTEGER", "300"),
            ("max_retries", "INTEGER NOT NULL", "0"),
            ("retry_delay_seconds", "INTEGER NOT NULL", "60"),
        ]:
            try:
                self._conn.execute(f"ALTER TABLE broker_jobs ADD COLUMN {col} {col_type} DEFAULT {default}")
            except sqlite3.OperationalError:
                pass

        # Migration: add attempt_number and scheduled_at to broker_runs
        for col, col_type, default in [
            ("attempt_number", "INTEGER NOT NULL", "1"),
            ("scheduled_at", "TEXT", None),
        ]:
            try:
                default_clause = f" DEFAULT {default}" if default else ""
                self._conn.execute(f"ALTER TABLE broker_runs ADD COLUMN {col} {col_type}{default_clause}")
            except sqlite3.OperationalError:
                pass

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
        hitl_enabled: bool = False,
        hitl_timeout_seconds: int = 300,
        max_retries: int = 0,
        retry_delay_seconds: int = 60,
    ) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        now = _now_iso()
        self._conn.execute(
            """INSERT INTO broker_jobs
               (id, name, trigger_type, cron_expr, timezone, enabled,
                prompt_template, session_id, config_profile,
                response_channel, overlap_policy, timeout_seconds,
                hitl_enabled, hitl_timeout_seconds, max_retries, retry_delay_seconds,
                created_at, updated_at)
               VALUES (?, ?, 'cron', ?, ?, 1, ?, ?, ?, 'log', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                name,
                cron_expr,
                timezone,
                prompt_template,
                session_id,
                config_profile,
                overlap_policy,
                timeout_seconds,
                1 if hitl_enabled else 0,
                hitl_timeout_seconds,
                max_retries,
                retry_delay_seconds,
                now,
                now,
            ),
        )
        self._conn.commit()
        return self.get_job(job_id)  # type: ignore[return-value]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM broker_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def list_jobs(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        if enabled_only:
            rows = self._conn.execute("SELECT * FROM broker_jobs WHERE enabled = 1 ORDER BY name").fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM broker_jobs ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def update_job(self, job_id: str, **fields: Any) -> None:
        allowed = {
            "name",
            "cron_expr",
            "timezone",
            "enabled",
            "prompt_template",
            "session_id",
            "config_profile",
            "overlap_policy",
            "timeout_seconds",
            "response_channel",
            "response_target",
            "hitl_enabled",
            "hitl_timeout_seconds",
            "max_retries",
            "retry_delay_seconds",
            "last_run_at",
            "next_run_at",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = _now_iso()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [job_id]
        self._conn.execute(f"UPDATE broker_jobs SET {set_clause} WHERE id = ?", values)
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
        return (row[0] if row else 0) > 0

    def create_run_if_no_overlap(
        self,
        *,
        job_id: str,
        trigger_source: str,
        prompt: str,
        session_id: str | None = None,
    ) -> str | None:
        """Atomically check for running runs and create a new one if none exist.

        Returns the run_id if created, or None if a run is already active (overlap).
        """
        run_id = str(uuid.uuid4())
        now = _now_iso()
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT COUNT(*) FROM broker_runs WHERE job_id = ? AND status = 'running'",
                (job_id,),
            ).fetchone()
            if (row[0] if row else 0) > 0:
                self._conn.execute("ROLLBACK")
                return None
            self._conn.execute(
                """INSERT INTO broker_runs
                   (id, job_id, trigger_source, prompt, session_id, status, started_at)
                   VALUES (?, ?, ?, ?, ?, 'running', ?)""",
                (run_id, job_id, trigger_source, prompt, session_id, now),
            )
            self._conn.execute("COMMIT")
            return run_id
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

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

    def set_run_response_info(
        self,
        run_id: str,
        *,
        response_channel: str,
        response_target: str | None,
    ) -> None:
        """Set the response routing info for a run."""
        self._conn.execute(
            "UPDATE broker_runs SET response_channel = ?, response_target = ? WHERE id = ?",
            (response_channel, response_target, run_id),
        )
        self._conn.commit()

    def mark_response_sent(self, run_id: str) -> None:
        self._conn.execute(
            "UPDATE broker_runs SET response_sent = 1 WHERE id = ?",
            (run_id,),
        )
        self._conn.commit()

    def mark_response_failed(self, run_id: str, *, error: str) -> None:
        self._conn.execute(
            "UPDATE broker_runs SET response_error = ? WHERE id = ?",
            (error, run_id),
        )
        self._conn.commit()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM broker_runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    # -- Question tracking (HITL) --

    def create_question(
        self,
        *,
        run_id: str,
        question_text: str,
        options: str | None = None,
        timeout_seconds: int = 300,
    ) -> str:
        qid = str(uuid.uuid4())
        now = datetime.now(UTC)
        timeout_at = (now + timedelta(seconds=timeout_seconds)).isoformat()
        self._conn.execute(
            """INSERT INTO broker_questions
               (id, run_id, question_text, options, status, asked_at, timeout_at)
               VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
            (qid, run_id, question_text, options, now.isoformat(), timeout_at),
        )
        self._conn.commit()
        return qid

    def get_question(self, question_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM broker_questions WHERE id = ?", (question_id,)).fetchone()
        if row is None:
            return None
        q = dict(row)
        # Auto-timeout expired pending questions
        if q["status"] == "pending" and q["timeout_at"] <= _now_iso():
            self._conn.execute(
                "UPDATE broker_questions SET status = 'timed_out' WHERE id = ? AND status = 'pending'",
                (question_id,),
            )
            self._conn.commit()
            q["status"] = "timed_out"
        return q

    def get_pending_question(self, run_id: str) -> dict[str, Any] | None:
        """Get the most recent pending question for a run."""
        row = self._conn.execute(
            "SELECT * FROM broker_questions WHERE run_id = ? AND status = 'pending' ORDER BY asked_at DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        q = dict(row)
        if q["timeout_at"] <= _now_iso():
            self._conn.execute(
                "UPDATE broker_questions SET status = 'timed_out' WHERE id = ? AND status = 'pending'",
                (q["id"],),
            )
            self._conn.commit()
            return None
        return q

    def answer_question(self, question_id: str, *, answer: str) -> bool:
        cursor = self._conn.execute(
            "UPDATE broker_questions SET answer = ?, status = 'answered', answered_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (answer, _now_iso(), question_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    # -- Retry support --

    def create_retry_run(
        self,
        *,
        job_id: str,
        trigger_source: str,
        prompt: str,
        session_id: str | None = None,
        attempt_number: int,
        scheduled_at: str,
    ) -> str:
        run_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO broker_runs
               (id, job_id, trigger_source, prompt, session_id, status,
                attempt_number, scheduled_at)
               VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)""",
            (run_id, job_id, trigger_source, prompt, session_id, attempt_number, scheduled_at),
        )
        self._conn.commit()
        return run_id

    def list_due_retries(self) -> list[dict[str, Any]]:
        now = _now_iso()
        rows = self._conn.execute(
            "SELECT * FROM broker_runs WHERE status = 'queued' "
            "AND scheduled_at IS NOT NULL AND scheduled_at <= ? "
            "ORDER BY scheduled_at",
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]

    def start_run(self, run_id: str) -> None:
        """Transition a queued run to running status."""
        self._conn.execute(
            "UPDATE broker_runs SET status = 'running', started_at = ? WHERE id = ?",
            (_now_iso(), run_id),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
