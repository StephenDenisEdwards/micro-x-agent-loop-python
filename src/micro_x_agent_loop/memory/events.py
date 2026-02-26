from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from loguru import logger

from micro_x_agent_loop.memory.event_sink import AsyncEventSink
from micro_x_agent_loop.memory.store import MemoryStore

EventCallback = Callable[[str, str, dict], None]
"""Signature: (session_id, event_type, payload) -> None"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class EventEmitter:
    def __init__(self, store: MemoryStore, sink: AsyncEventSink | None = None):
        self._store = store
        self._sink = sink
        self._callbacks: dict[str | None, list[EventCallback]] = {}

    # -- Subscriber API --

    def on(self, event_type: str, callback: EventCallback) -> None:
        """Register *callback* for a specific *event_type*."""
        self._callbacks.setdefault(event_type, []).append(callback)

    def on_all(self, callback: EventCallback) -> None:
        """Register *callback* for **all** event types."""
        self._callbacks.setdefault(None, []).append(callback)

    def off(self, event_type: str | None, callback: EventCallback) -> None:
        """Remove a previously registered callback.

        Pass *event_type=None* to remove a wildcard listener.
        """
        listeners = self._callbacks.get(event_type)
        if listeners is not None:
            try:
                listeners.remove(callback)
            except ValueError:
                pass

    # -- Emit --

    def emit(self, session_id: str, event_type: str, payload: dict) -> None:
        # Persist first (DB is source of truth).
        if self._sink is not None:
            self._sink.emit(session_id, event_type, payload)
        else:
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

        # Notify subscribers (best-effort — never let a callback break the pipeline).
        for cb in self._callbacks.get(event_type, []):
            try:
                cb(session_id, event_type, payload)
            except Exception as ex:
                logger.warning(f"Event callback error for {event_type}: {ex}")
        for cb in self._callbacks.get(None, []):
            try:
                cb(session_id, event_type, payload)
            except Exception as ex:
                logger.warning(f"Wildcard event callback error for {event_type}: {ex}")
