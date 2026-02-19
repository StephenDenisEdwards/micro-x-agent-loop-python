from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

from micro_x_agent_loop.memory.store import MemoryStore


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class AsyncEventSink:
    def __init__(self, store: MemoryStore, *, batch_size: int = 50, flush_interval_seconds: float = 0.5):
        self._store = store
        self._batch_size = max(1, batch_size)
        self._flush_interval_seconds = max(0.05, flush_interval_seconds)
        self._queue: asyncio.Queue[tuple[str, str, dict]] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._closed = False

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    def emit(self, session_id: str, event_type: str, payload: dict) -> None:
        if self._closed:
            return
        self._queue.put_nowait((session_id, event_type, payload))

    async def close(self) -> None:
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._flush_all()

    async def _run(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._flush_interval_seconds)
                await self._flush_once()
        except asyncio.CancelledError:
            raise

    async def _flush_all(self) -> None:
        while not self._queue.empty():
            await self._flush_once(force=True)

    async def _flush_once(self, *, force: bool = False) -> None:
        items: list[tuple[str, str, dict]] = []
        while len(items) < self._batch_size and not self._queue.empty():
            items.append(self._queue.get_nowait())

        if not items and not force:
            return

        if not items:
            return

        params: list[tuple[str, str, str, str, str]] = []
        now = _utc_now()
        for session_id, event_type, payload in items:
            params.append((str(uuid4()), session_id, event_type, json.dumps(payload, ensure_ascii=True), now))

        with self._store.transaction():
            self._store.executemany(
                """
                INSERT INTO events (id, session_id, type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                params,
            )
