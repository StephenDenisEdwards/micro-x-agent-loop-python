from __future__ import annotations

import json
from uuid import uuid4

from micro_x_agent_loop.compaction import estimate_tokens
from micro_x_agent_loop.memory.events import EventEmitter, utc_now
from micro_x_agent_loop.memory.store import MemoryStore


class SessionManager:
    def __init__(self, store: MemoryStore, model: str, events: EventEmitter):
        self._store = store
        self._model = model
        self._events = events

    def get_session(self, session_id: str) -> dict | None:
        row = self._store.execute(
            "SELECT * FROM sessions WHERE id = ? LIMIT 1",
            (session_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def list_sessions(self, *, limit: int = 50) -> list[dict]:
        rows = self._store.execute(
            """
            SELECT id, parent_session_id, created_at, updated_at, status, model
            FROM sessions
            ORDER BY updated_at DESC, created_at DESC
            LIMIT ?
            """,
            (max(1, limit),),
        ).fetchall()
        return [dict(row) for row in rows]

    def create_session(
        self,
        session_id: str | None = None,
        *,
        parent_session_id: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        sid = session_id or str(uuid4())
        now = utc_now()
        self._store.execute(
            """
            INSERT INTO sessions (id, parent_session_id, created_at, updated_at, status, model, metadata_json)
            VALUES (?, ?, ?, ?, 'active', ?, ?)
            """,
            (sid, parent_session_id, now, now, self._model, json.dumps(metadata or {}, ensure_ascii=True)),
        )
        self._store.commit()
        self._events.emit(sid, "session.started", {"session_id": sid, "parent_session_id": parent_session_id})
        return sid

    def load_or_create(self, session_id: str) -> str:
        if self.get_session(session_id) is not None:
            return session_id
        return self.create_session(session_id)

    def append_message(self, session_id: str, role: str, content: str | list[dict]) -> tuple[str, int]:
        row = self._store.execute(
            "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        next_seq = int(row["max_seq"]) + 1
        message_id = str(uuid4())
        now = utc_now()
        content_json = json.dumps(content, ensure_ascii=True)
        token_estimate = max(0, estimate_tokens([{"role": role, "content": content}]))
        self._store.execute(
            """
            INSERT INTO messages (id, session_id, seq, role, content_json, created_at, token_estimate)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (message_id, session_id, next_seq, role, content_json, now, token_estimate),
        )
        self._store.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (now, session_id),
        )
        self._store.commit()
        self._events.emit(
            session_id,
            "message.appended",
            {"session_id": session_id, "message_id": message_id, "seq": next_seq, "role": role},
        )
        return message_id, next_seq

    def load_messages(self, session_id: str) -> list[dict]:
        rows = self._store.execute(
            """
            SELECT role, content_json
            FROM messages
            WHERE session_id = ?
            ORDER BY seq ASC
            """,
            (session_id,),
        ).fetchall()
        return [{"role": row["role"], "content": json.loads(row["content_json"])} for row in rows]

    def record_tool_call(
        self,
        session_id: str,
        *,
        message_id: str | None,
        tool_name: str,
        tool_input: dict,
        result_text: str,
        is_error: bool,
        tool_call_id: str | None = None,
    ) -> str:
        call_id = tool_call_id or str(uuid4())
        now = utc_now()
        self._store.execute(
            """
            INSERT INTO tool_calls (id, session_id, message_id, tool_name, input_json, result_text, is_error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                call_id,
                session_id,
                message_id,
                tool_name,
                json.dumps(tool_input, ensure_ascii=True),
                result_text,
                1 if is_error else 0,
                now,
            ),
        )
        self._store.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (now, session_id),
        )
        self._store.commit()
        return call_id

    def fork_session(self, source_session_id: str, new_session_id: str | None = None) -> str:
        source = self.get_session(source_session_id)
        if source is None:
            raise ValueError(f"Session does not exist: {source_session_id}")

        fork_id = self.create_session(
            new_session_id,
            parent_session_id=source_session_id,
            metadata={"forked_from": source_session_id},
        )
        rows = self._store.execute(
            """
            SELECT seq, role, content_json, token_estimate, created_at
            FROM messages
            WHERE session_id = ?
            ORDER BY seq ASC
            """,
            (source_session_id,),
        ).fetchall()

        if rows:
            params: list[tuple] = []
            for row in rows:
                params.append(
                    (
                        str(uuid4()),
                        fork_id,
                        row["seq"],
                        row["role"],
                        row["content_json"],
                        row["created_at"],
                        row["token_estimate"],
                    )
                )
            self._store.executemany(
                """
                INSERT INTO messages (id, session_id, seq, role, content_json, created_at, token_estimate)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
            self._store.commit()
        return fork_id
