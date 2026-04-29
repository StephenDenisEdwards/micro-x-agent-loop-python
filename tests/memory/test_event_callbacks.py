"""Tests for the EventEmitter callback/subscriber API."""

import unittest

from micro_x_agent_loop.memory.events import EventEmitter
from micro_x_agent_loop.memory.store import MemoryStore


class EventCallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self._store = MemoryStore(":memory:")
        self._store.execute(
            """
            INSERT INTO sessions (id, parent_session_id, created_at, updated_at, status, model, metadata_json)
            VALUES (?, NULL, ?, ?, 'active', ?, '{}')
            """,
            ("s1", "2026-02-26T00:00:00+00:00", "2026-02-26T00:00:00+00:00", "m"),
        )
        self._store.commit()

    def tearDown(self) -> None:
        self._store.close()

    def test_on_receives_matching_events(self) -> None:
        emitter = EventEmitter(self._store)
        received: list[tuple] = []
        emitter.on("tool.started", lambda sid, et, p: received.append((sid, et, p)))

        emitter.emit("s1", "tool.started", {"tool": "write_file"})
        emitter.emit("s1", "tool.completed", {"tool": "write_file"})

        self.assertEqual(1, len(received))
        self.assertEqual("tool.started", received[0][1])

    def test_on_all_receives_all_events(self) -> None:
        emitter = EventEmitter(self._store)
        received: list[str] = []
        emitter.on_all(lambda sid, et, p: received.append(et))

        emitter.emit("s1", "tool.started", {})
        emitter.emit("s1", "tool.completed", {})
        emitter.emit("s1", "checkpoint.created", {})

        self.assertEqual(["tool.started", "tool.completed", "checkpoint.created"], received)

    def test_multiple_callbacks_for_same_event(self) -> None:
        emitter = EventEmitter(self._store)
        log_a: list[str] = []
        log_b: list[str] = []
        emitter.on("tool.started", lambda s, e, p: log_a.append(e))
        emitter.on("tool.started", lambda s, e, p: log_b.append(e))

        emitter.emit("s1", "tool.started", {})

        self.assertEqual(1, len(log_a))
        self.assertEqual(1, len(log_b))

    def test_off_removes_callback(self) -> None:
        emitter = EventEmitter(self._store)
        received: list[str] = []

        def cb(sid: str, et: str, p: object) -> None:
            received.append(et)

        emitter.on("tool.started", cb)
        emitter.off("tool.started", cb)

        emitter.emit("s1", "tool.started", {})

        self.assertEqual([], received)

    def test_off_wildcard_removes_on_all_callback(self) -> None:
        emitter = EventEmitter(self._store)
        received: list[str] = []

        def cb(sid: str, et: str, p: object) -> None:
            received.append(et)

        emitter.on_all(cb)
        emitter.off(None, cb)

        emitter.emit("s1", "tool.started", {})

        self.assertEqual([], received)

    def test_off_nonexistent_callback_is_safe(self) -> None:
        emitter = EventEmitter(self._store)
        emitter.off("tool.started", lambda s, e, p: None)  # should not raise

    def test_callback_error_does_not_break_emit(self) -> None:
        emitter = EventEmitter(self._store)
        good_received: list[str] = []

        def bad_cb(sid: str, et: str, p: dict) -> None:
            raise RuntimeError("boom")

        emitter.on("tool.started", bad_cb)
        emitter.on("tool.started", lambda s, e, p: good_received.append(e))

        emitter.emit("s1", "tool.started", {})

        # The second callback should still have fired despite the first raising.
        self.assertEqual(["tool.started"], good_received)

    def test_wildcard_callback_error_does_not_break_emit(self) -> None:
        emitter = EventEmitter(self._store)
        good_received: list[str] = []

        emitter.on_all(lambda s, e, p: (_ for _ in ()).throw(RuntimeError("boom")))
        emitter.on_all(lambda s, e, p: good_received.append(e))

        emitter.emit("s1", "tool.started", {})

        self.assertEqual(["tool.started"], good_received)

    def test_emit_persists_to_db_and_notifies(self) -> None:
        emitter = EventEmitter(self._store)
        received: list[str] = []
        emitter.on("custom.event", lambda s, e, p: received.append(e))

        emitter.emit("s1", "custom.event", {"key": "value"})

        # Callback fired
        self.assertEqual(["custom.event"], received)
        # Event persisted to DB
        row = self._store.execute("SELECT COUNT(*) AS c FROM events WHERE type = ?", ("custom.event",)).fetchone()
        self.assertEqual(1, int(row["c"]))

    def test_callback_receives_correct_payload(self) -> None:
        emitter = EventEmitter(self._store)
        payloads: list[dict] = []
        emitter.on("tool.started", lambda s, e, p: payloads.append(p))

        emitter.emit("s1", "tool.started", {"tool_name": "write_file", "id": "123"})

        self.assertEqual(1, len(payloads))
        self.assertEqual("write_file", payloads[0]["tool_name"])
        self.assertEqual("123", payloads[0]["id"])


if __name__ == "__main__":
    unittest.main()
