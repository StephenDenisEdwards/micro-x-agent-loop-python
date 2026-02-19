from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from micro_x_agent_loop.memory.events import EventEmitter, utc_now
from micro_x_agent_loop.memory.store import MemoryStore


class CheckpointManager:
    def __init__(
        self,
        store: MemoryStore,
        events: EventEmitter,
        *,
        working_directory: str | None,
        enabled: bool,
        write_tools_only: bool,
    ):
        self._store = store
        self._events = events
        self._working_directory = Path(working_directory or Path.cwd()).resolve()
        self._enabled = enabled
        self._write_tools_only = write_tools_only

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def write_tools_only(self) -> bool:
        return self._write_tools_only

    def create_checkpoint(self, session_id: str, user_message_id: str, *, scope: dict | None = None) -> str:
        checkpoint_id = str(uuid4())
        now = utc_now()
        self._store.execute(
            """
            INSERT INTO checkpoints (id, session_id, user_message_id, created_at, scope_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (checkpoint_id, session_id, user_message_id, now, json.dumps(scope or {}, ensure_ascii=True)),
        )
        self._store.commit()
        self._events.emit(
            session_id,
            "checkpoint.created",
            {"session_id": session_id, "checkpoint_id": checkpoint_id},
        )
        return checkpoint_id

    def maybe_track_tool_input(self, checkpoint_id: str, tool_input: dict) -> list[str]:
        path_val = tool_input.get("path")
        if not isinstance(path_val, str) or not path_val.strip():
            return []
        resolved = self._resolve_path(path_val)
        self._snapshot_file(checkpoint_id, resolved)
        return [str(resolved)]

    def rewind_files(self, checkpoint_id: str) -> tuple[str, list[dict[str, str]]]:
        row = self._store.execute(
            "SELECT session_id FROM checkpoints WHERE id = ? LIMIT 1",
            (checkpoint_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Checkpoint does not exist: {checkpoint_id}")

        session_id = str(row["session_id"])
        self._events.emit(session_id, "rewind.started", {"checkpoint_id": checkpoint_id})
        files = self._store.execute(
            """
            SELECT path, existed_before, backup_blob
            FROM checkpoint_files
            WHERE checkpoint_id = ?
            ORDER BY path ASC
            """,
            (checkpoint_id,),
        ).fetchall()

        outcomes: list[dict[str, str]] = []
        for row in files:
            path = Path(str(row["path"]))
            existed_before = bool(row["existed_before"])
            status = "skipped"
            detail = ""
            try:
                if existed_before:
                    backup_blob = row["backup_blob"]
                    if backup_blob is None:
                        status = "failed"
                        detail = "missing backup blob"
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(backup_blob)
                        status = "restored"
                else:
                    if path.exists():
                        path.unlink()
                        status = "removed"
                    else:
                        status = "skipped"
            except Exception as ex:
                status = "failed"
                detail = str(ex)

            outcome = {"path": str(path), "status": status, "detail": detail}
            outcomes.append(outcome)
            self._events.emit(
                session_id,
                "rewind.file_restored",
                {
                    "checkpoint_id": checkpoint_id,
                    "path": str(path),
                    "status": status,
                    "detail": detail,
                },
            )

        self._events.emit(
            session_id,
            "rewind.completed",
            {"checkpoint_id": checkpoint_id, "results_count": len(outcomes)},
        )
        return session_id, outcomes

    def _snapshot_file(self, checkpoint_id: str, path: Path) -> None:
        checkpoint_row = self._store.execute(
            "SELECT session_id FROM checkpoints WHERE id = ? LIMIT 1",
            (checkpoint_id,),
        ).fetchone()
        if checkpoint_row is None:
            raise ValueError(f"Checkpoint does not exist: {checkpoint_id}")
        session_id = str(checkpoint_row["session_id"])

        existing = self._store.execute(
            """
            SELECT 1
            FROM checkpoint_files
            WHERE checkpoint_id = ? AND path = ?
            LIMIT 1
            """,
            (checkpoint_id, str(path)),
        ).fetchone()
        if existing is not None:
            return

        existed_before = path.exists()
        backup_blob = path.read_bytes() if existed_before else None
        self._store.execute(
            """
            INSERT INTO checkpoint_files (checkpoint_id, path, existed_before, backup_blob, backup_path)
            VALUES (?, ?, ?, ?, NULL)
            """,
            (checkpoint_id, str(path), 1 if existed_before else 0, backup_blob),
        )
        self._store.commit()
        self._events.emit(
            session_id,
            "checkpoint.file_tracked",
            {"checkpoint_id": checkpoint_id, "path": str(path), "existed_before": existed_before},
        )

    def _resolve_path(self, path_value: str) -> Path:
        path = Path(path_value)
        candidate = path if path.is_absolute() else self._working_directory / path
        resolved = candidate.resolve()
        if not self._is_within_working_directory(resolved):
            raise ValueError(f"Path is outside working directory: {resolved}")
        return resolved

    def _is_within_working_directory(self, path: Path) -> bool:
        try:
            path.relative_to(self._working_directory)
            return True
        except ValueError:
            return False
