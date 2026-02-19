import asyncio
import unittest

from micro_x_agent_loop.memory.event_sink import AsyncEventSink
from micro_x_agent_loop.memory.store import MemoryStore


class EventSinkTests(unittest.TestCase):
    def test_event_sink_flushes_events(self) -> None:
        store = MemoryStore(":memory:")
        store.execute(
            """
            INSERT INTO sessions (id, parent_session_id, created_at, updated_at, status, model, metadata_json)
            VALUES (?, NULL, ?, ?, 'active', ?, '{}')
            """,
            ("s1", "2026-02-19T00:00:00+00:00", "2026-02-19T00:00:00+00:00", "m"),
        )
        store.commit()
        sink = AsyncEventSink(store, batch_size=10, flush_interval_seconds=0.05)

        async def scenario() -> None:
            await sink.start()
            sink.emit("s1", "event.one", {"x": 1})
            sink.emit("s1", "event.two", {"y": 2})
            await asyncio.sleep(0.12)
            await sink.close()

        asyncio.run(scenario())

        row = store.execute("SELECT COUNT(*) AS c FROM events WHERE session_id = ?", ("s1",)).fetchone()
        self.assertEqual(2, int(row["c"]))
        store.close()


if __name__ == "__main__":
    unittest.main()
