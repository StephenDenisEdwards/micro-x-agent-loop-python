from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from micro_x_agent_loop.memory.store import MemoryStore


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class EventEmitter:
    def __init__(self, store: MemoryStore):
        self._store = store

    def emit(self, session_id: str, event_type: str, payload: dict) -> None:
        self._store.execute(
            """
            INSERT INTO events (id, session_id, type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                session_id,
                event_type,
                json.dumps(payload, ensure_ascii=True),
                utc_now(),
            ),
        )
        self._store.commit()
