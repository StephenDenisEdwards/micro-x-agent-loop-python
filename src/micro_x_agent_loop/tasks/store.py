from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from micro_x_agent_loop.tasks.models import AgentStatus, ClaimResult, Task, TaskStatus


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class TaskStore:
    """SQLite-backed storage for decomposed tasks.

    Implements the storage contract from task-decomposition-implementation-guide.md
    Section 4, adapted from file-based JSON to SQLite.  Concurrency is handled via
    ``BEGIN IMMEDIATE`` transactions instead of file locking.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self._db_path), check_same_thread=False, isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._initialize_schema()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Transaction helper
    # ------------------------------------------------------------------

    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        """Execute a block inside ``BEGIN IMMEDIATE`` for write serialisation."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_task(
        self,
        list_id: str,
        subject: str,
        description: str,
        active_form: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        """Create a new task with auto-incrementing ID.

        Uses the high-water-mark to prevent ID reuse after deletion
        (guide Section 4.3).
        """
        now = _now_iso()
        metadata_json = json.dumps(metadata or {})

        with self.transaction():
            hwm = self._read_hwm(list_id)
            max_id = self._max_task_id(list_id)
            next_id = max(hwm, max_id) + 1

            self._conn.execute(
                """
                INSERT INTO tasks (id, list_id, subject, description, status,
                                   active_form, owner, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                """,
                (next_id, list_id, subject, description, TaskStatus.PENDING.value,
                 active_form, metadata_json, now, now),
            )
            self._write_hwm(list_id, next_id)

        return Task(
            id=str(next_id),
            subject=subject,
            description=description,
            status=TaskStatus.PENDING,
            blocks=[],
            blocked_by=[],
            active_form=active_form,
            owner=None,
            metadata=metadata,
        )

    def get_task(self, list_id: str, task_id: str) -> Task | None:
        """Retrieve a single task by ID, or ``None`` if not found."""
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE id = ? AND list_id = ?",
            (int(task_id), list_id),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_task(row, list_id)

    def list_tasks(self, list_id: str) -> list[Task]:
        """Return all tasks for *list_id*, excluding internal tasks."""
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE list_id = ? ORDER BY id",
            (list_id,),
        ).fetchall()

        tasks: list[Task] = []
        for row in rows:
            meta = json.loads(row["metadata_json"])
            if meta.get("_internal"):
                continue
            tasks.append(self._row_to_task(row, list_id))
        return tasks

    def update_task(self, list_id: str, task_id: str, **updates: Any) -> Task | None:
        """Apply field updates to an existing task.

        Accepted keyword arguments: ``subject``, ``description``, ``status``,
        ``active_form``, ``owner``, ``metadata``.

        Returns the updated task, or ``None`` if not found.
        """
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE id = ? AND list_id = ?",
            (int(task_id), list_id),
        ).fetchone()
        if row is None:
            return None

        sets: list[str] = []
        params: list[Any] = []

        for col in ("subject", "description", "active_form", "owner"):
            if col in updates:
                sets.append(f"{col} = ?")
                params.append(updates[col])

        if "status" in updates:
            sets.append("status = ?")
            status_val = updates["status"]
            if isinstance(status_val, TaskStatus):
                params.append(status_val.value)
            else:
                params.append(status_val)

        if "metadata" in updates:
            existing_meta: dict[str, Any] = json.loads(row["metadata_json"])
            new_meta: dict[str, Any] = updates["metadata"] or {}
            for k, v in new_meta.items():
                if v is None:
                    existing_meta.pop(k, None)
                else:
                    existing_meta[k] = v
            sets.append("metadata_json = ?")
            params.append(json.dumps(existing_meta))

        if sets:
            sets.append("updated_at = ?")
            params.append(_now_iso())
            params.extend([int(task_id), list_id])
            self._conn.execute(
                f"UPDATE tasks SET {', '.join(sets)} WHERE id = ? AND list_id = ?",
                tuple(params),
            )
            self._conn.commit()

        return self.get_task(list_id, task_id)

    def delete_task(self, list_id: str, task_id: str) -> bool:
        """Permanently remove a task and cascade-clean dependency references.

        Updates the high-water-mark so the ID is never reused (guide Section 4.3).
        """
        tid = int(task_id)
        with self.transaction():
            row = self._conn.execute(
                "SELECT id FROM tasks WHERE id = ? AND list_id = ?",
                (tid, list_id),
            ).fetchone()
            if row is None:
                return False

            # Update HWM before deletion
            hwm = self._read_hwm(list_id)
            if tid > hwm:
                self._write_hwm(list_id, tid)

            # Cascade: remove all dependency edges involving this task
            self._conn.execute(
                "DELETE FROM task_dependencies WHERE (from_task_id = ? OR to_task_id = ?) AND list_id = ?",
                (tid, tid, list_id),
            )
            # Delete the task itself
            self._conn.execute(
                "DELETE FROM tasks WHERE id = ? AND list_id = ?",
                (tid, list_id),
            )
        return True

    def block_task(self, list_id: str, from_task_id: str, to_task_id: str) -> bool:
        """Create a bidirectional dependency: *from_task* blocks *to_task*.

        Adds ``to_task_id`` to ``from_task.blocks`` and ``from_task_id`` to
        ``to_task.blocked_by`` (guide Section 6.1).
        """
        fid = int(from_task_id)
        tid = int(to_task_id)

        # Verify both tasks exist
        for check_id in (fid, tid):
            row = self._conn.execute(
                "SELECT id FROM tasks WHERE id = ? AND list_id = ?",
                (check_id, list_id),
            ).fetchone()
            if row is None:
                return False

        # Insert dependency edge (from blocks to => from_task.blocks has to, to_task.blocked_by has from)
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO task_dependencies (from_task_id, to_task_id, list_id) VALUES (?, ?, ?)",
                (fid, tid, list_id),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            return False
        return True

    def reset_task_list(self, list_id: str) -> None:
        """Delete all tasks and dependencies for *list_id*, preserving the high-water-mark."""
        with self.transaction():
            max_id = self._max_task_id(list_id)
            hwm = self._read_hwm(list_id)
            self._write_hwm(list_id, max(hwm, max_id))
            self._conn.execute("DELETE FROM task_dependencies WHERE list_id = ?", (list_id,))
            self._conn.execute("DELETE FROM tasks WHERE list_id = ?", (list_id,))

    # ------------------------------------------------------------------
    # Multi-agent coordination (guide Section 9)
    # ------------------------------------------------------------------

    def claim_task(
        self, list_id: str, task_id: str, agent_id: str,
        *, check_busy: bool = False,
    ) -> ClaimResult:
        """Atomically claim a task for an agent.

        Checks (in order, per guide Section 9.1):
        1. Task exists
        2. Not already claimed by another agent (same-agent re-claim OK)
        3. Not already completed
        4. No unresolved blockers
        5. (Optional) Agent not busy with other open tasks

        When *check_busy* is ``True``, the entire operation runs inside
        a list-level transaction for atomicity (guide Section 9.2).
        """
        with self.transaction():
            task = self.get_task(list_id, task_id)
            if task is None:
                return ClaimResult(success=False, reason="task_not_found")

            if task.status == TaskStatus.COMPLETED:
                return ClaimResult(success=False, reason="already_resolved", task=task)

            if task.owner is not None and task.owner != agent_id:
                return ClaimResult(success=False, reason="already_claimed", task=task)

            # Check unresolved blockers
            all_tasks = self._list_all_tasks(list_id)
            unresolved_ids = {t.id for t in all_tasks if t.status != TaskStatus.COMPLETED}
            active_blockers = [bid for bid in task.blocked_by if bid in unresolved_ids]
            if active_blockers:
                return ClaimResult(
                    success=False, reason="blocked", task=task,
                    blocked_by_tasks=active_blockers,
                )

            # Optional busy check
            if check_busy:
                busy_tasks = [
                    t.id for t in all_tasks
                    if t.owner == agent_id
                    and t.status == TaskStatus.IN_PROGRESS
                    and t.id != task_id
                ]
                if busy_tasks:
                    return ClaimResult(
                        success=False, reason="agent_busy", task=task,
                        busy_with_tasks=busy_tasks,
                    )

            # Claim: set owner and status
            self._conn.execute(
                "UPDATE tasks SET owner = ?, status = ?, updated_at = ? "
                "WHERE id = ? AND list_id = ?",
                (agent_id, TaskStatus.IN_PROGRESS.value, _now_iso(),
                 int(task_id), list_id),
            )

        return ClaimResult(
            success=True,
            task=self.get_task(list_id, task_id),
        )

    def get_agent_statuses(self, list_id: str, agent_ids: list[str]) -> list[AgentStatus]:
        """Return idle/busy status for each agent based on task ownership.

        An agent is "busy" if it owns at least one non-completed task (guide
        Section 9.3).
        """
        all_tasks = self._list_all_tasks(list_id)
        statuses: list[AgentStatus] = []
        for agent_id in agent_ids:
            owned = [
                t.id for t in all_tasks
                if t.owner == agent_id and t.status != TaskStatus.COMPLETED
            ]
            statuses.append(AgentStatus(
                agent_id=agent_id,
                name=agent_id,
                status="busy" if owned else "idle",
                current_tasks=owned,
            ))
        return statuses

    def unassign_agent_tasks(
        self, list_id: str, agent_id: str, reason: str = "shutdown",
    ) -> tuple[list[Task], str]:
        """Reset all non-completed tasks owned by an agent to pending/unowned.

        Returns the unassigned tasks and a notification message for the team
        lead (guide Section 9.5).
        """
        all_tasks = self._list_all_tasks(list_id)
        unassigned: list[Task] = []

        with self.transaction():
            for task in all_tasks:
                if task.owner == agent_id and task.status != TaskStatus.COMPLETED:
                    self._conn.execute(
                        "UPDATE tasks SET owner = NULL, status = ?, updated_at = ? "
                        "WHERE id = ? AND list_id = ?",
                        (TaskStatus.PENDING.value, _now_iso(),
                         int(task.id), list_id),
                    )
                    unassigned.append(task)

        if not unassigned:
            msg = f"{agent_id} was {reason}. No tasks were unassigned."
        else:
            task_list = ", ".join(
                f'#{t.id} "{t.subject}"' for t in unassigned
            )
            msg = (
                f"{agent_id} was {reason}. {len(unassigned)} task(s) were "
                f"unassigned: {task_list}. Use task_list to check availability "
                f"and task_update with owner to reassign them."
            )
        return unassigned, msg

    def _list_all_tasks(self, list_id: str) -> list[Task]:
        """List all tasks including internal ones (for multi-agent checks)."""
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE list_id = ? ORDER BY id",
            (list_id,),
        ).fetchall()
        return [self._row_to_task(row, list_id) for row in rows]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _row_to_task(self, row: sqlite3.Row, list_id: str) -> Task:
        """Convert a database row + dependency lookups into a ``Task``."""
        tid = row["id"]
        blocks = [
            str(r["to_task_id"])
            for r in self._conn.execute(
                "SELECT to_task_id FROM task_dependencies WHERE from_task_id = ? AND list_id = ?",
                (tid, list_id),
            ).fetchall()
        ]
        blocked_by = [
            str(r["from_task_id"])
            for r in self._conn.execute(
                "SELECT from_task_id FROM task_dependencies WHERE to_task_id = ? AND list_id = ?",
                (tid, list_id),
            ).fetchall()
        ]
        meta_raw = row["metadata_json"]
        meta: dict[str, Any] = json.loads(meta_raw) if meta_raw else {}

        return Task(
            id=str(tid),
            subject=row["subject"],
            description=row["description"],
            status=TaskStatus(row["status"]),
            blocks=blocks,
            blocked_by=blocked_by,
            active_form=row["active_form"],
            owner=row["owner"],
            metadata=meta if meta else None,
        )

    def _read_hwm(self, list_id: str) -> int:
        row = self._conn.execute(
            "SELECT value FROM high_water_marks WHERE list_id = ?",
            (list_id,),
        ).fetchone()
        return int(row["value"]) if row else 0

    def _write_hwm(self, list_id: str, value: int) -> None:
        self._conn.execute(
            "INSERT INTO high_water_marks (list_id, value) VALUES (?, ?) "
            "ON CONFLICT(list_id) DO UPDATE SET value = ?",
            (list_id, value, value),
        )

    def _max_task_id(self, list_id: str) -> int:
        row = self._conn.execute(
            "SELECT MAX(id) as max_id FROM tasks WHERE list_id = ?",
            (list_id,),
        ).fetchone()
        return int(row["max_id"]) if row and row["max_id"] is not None else 0

    def _initialize_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER NOT NULL,
                list_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'in_progress', 'completed')),
                active_form TEXT,
                owner TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (id, list_id)
            );

            CREATE TABLE IF NOT EXISTS task_dependencies (
                from_task_id INTEGER NOT NULL,
                to_task_id INTEGER NOT NULL,
                list_id TEXT NOT NULL,
                PRIMARY KEY (from_task_id, to_task_id, list_id)
            );

            CREATE TABLE IF NOT EXISTS high_water_marks (
                list_id TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            );
            """
        )
