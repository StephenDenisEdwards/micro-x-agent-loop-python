from __future__ import annotations

import json
from datetime import datetime
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
        if row is None:
            return None
        session = dict(row)
        session["title"] = self._extract_title(session.get("metadata_json", "{}"), session["created_at"])
        return session

    def list_sessions(self, *, limit: int = 50) -> list[dict]:
        rows = self._store.execute(
            """
            SELECT id, parent_session_id, created_at, updated_at, status, model, metadata_json
            FROM sessions
            ORDER BY updated_at DESC, created_at DESC
            LIMIT ?
            """,
            (max(1, limit),),
        ).fetchall()
        results: list[dict] = []
        for row in rows:
            session = dict(row)
            session["title"] = self._extract_title(session.get("metadata_json", "{}"), session["created_at"])
            results.append(session)
        return results

    def create_session(
        self,
        session_id: str | None = None,
        *,
        parent_session_id: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        sid = session_id or str(uuid4())
        now = utc_now()
        full_metadata = dict(metadata or {})
        full_metadata.setdefault("title", self._default_title(now))
        self._store.execute(
            """
            INSERT INTO sessions (id, parent_session_id, created_at, updated_at, status, model, metadata_json)
            VALUES (?, ?, ?, ?, 'active', ?, ?)
            """,
            (sid, parent_session_id, now, now, self._model, json.dumps(full_metadata, ensure_ascii=True)),
        )
        self._store.commit()
        self._events.emit(sid, "session.started", {"session_id": sid, "parent_session_id": parent_session_id})
        return sid

    def set_session_title(self, session_id: str, title: str) -> None:
        row = self._store.execute(
            "SELECT metadata_json FROM sessions WHERE id = ? LIMIT 1",
            (session_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Session does not exist: {session_id}")

        metadata = self._parse_metadata(row["metadata_json"])
        metadata["title"] = title.strip()
        now = utc_now()
        self._store.execute(
            "UPDATE sessions SET metadata_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(metadata, ensure_ascii=True), now, session_id),
        )
        self._store.commit()
        self._events.emit(
            session_id,
            "session.renamed",
            {"session_id": session_id, "title": metadata["title"]},
        )

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

    def build_session_summary(self, session_id: str) -> dict:
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"Session does not exist: {session_id}")

        rows = self._store.execute(
            """
            SELECT role, content_json, seq
            FROM messages
            WHERE session_id = ?
            ORDER BY seq ASC
            """,
            (session_id,),
        ).fetchall()
        checkpoint_row = self._store.execute(
            "SELECT COUNT(*) AS c FROM checkpoints WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        checkpoint_count = int(checkpoint_row["c"]) if checkpoint_row is not None else 0

        user_count = 0
        assistant_count = 0
        last_user_preview = ""
        last_assistant_preview = ""

        for row in rows:
            role = str(row["role"])
            content_preview = self._preview_content(row["content_json"])
            if role == "user":
                user_count += 1
                last_user_preview = content_preview
            elif role == "assistant":
                assistant_count += 1
                last_assistant_preview = content_preview

        return {
            "session_id": session_id,
            "title": session.get("title", session_id),
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
            "message_count": len(rows),
            "user_message_count": user_count,
            "assistant_message_count": assistant_count,
            "checkpoint_count": checkpoint_count,
            "last_user_preview": last_user_preview,
            "last_assistant_preview": last_assistant_preview,
        }

    def fork_session(self, source_session_id: str, new_session_id: str | None = None) -> str:
        source = self.get_session(source_session_id)
        if source is None:
            raise ValueError(f"Session does not exist: {source_session_id}")

        source_title = source.get("title") or source_session_id
        now = utc_now()
        fork_id = self.create_session(
            new_session_id,
            parent_session_id=source_session_id,
            metadata={
                "forked_from": source_session_id,
                "title": f"Fork of {source_title} ({now[:16].replace('T', ' ')})",
            },
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

    def _default_title(self, iso_timestamp: str) -> str:
        return f"Session {iso_timestamp[:16].replace('T', ' ')}"

    def _extract_title(self, metadata_json: str, created_at: str) -> str:
        metadata = self._parse_metadata(metadata_json)
        title = metadata.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        return self._default_title(created_at)

    def _parse_metadata(self, metadata_json: str) -> dict:
        try:
            parsed = json.loads(metadata_json)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        return {}

    def _preview_content(self, content_json: str, max_chars: int = 140) -> str:
        try:
            content = json.loads(content_json)
        except Exception:
            return ""

        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type")
                    if block_type == "text":
                        parts.append(str(block.get("text", "")))
                    elif block_type == "tool_use":
                        parts.append(f"[tool:{block.get('name', '')}]")
                    elif block_type == "tool_result":
                        parts.append("[tool_result]")
            text = " ".join(p for p in parts if p).strip()
        else:
            text = str(content)

        text = " ".join(text.split())
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3] + "..."
