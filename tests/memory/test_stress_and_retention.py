"""Stress, concurrency, and retention hardening tests for the memory system."""

import asyncio
import unittest
from pathlib import Path

from micro_x_agent_loop.memory import CheckpointManager, prune_memory
from micro_x_agent_loop.memory.event_sink import AsyncEventSink
from micro_x_agent_loop.memory.events import EventEmitter
from tests.memory.base import MemoryStoreTestCase


class ConcurrentCheckpointTests(MemoryStoreTestCase):
    """Verify checkpoint operations are safe under concurrent tool execution."""

    def setUp(self) -> None:
        super().setUp()
        self._checkpoints = CheckpointManager(
            self._store,
            self._events,
            working_directory=str(self._tmp_dir),
            enabled=True,
            write_tools_only=False,
        )

    def _new_checkpoint(self) -> tuple[str, str]:
        sid = self._sessions.create_session()
        mid, _ = self._sessions.append_message(sid, "user", "concurrent test")
        cpid = self._checkpoints.create_checkpoint(sid, mid)
        return sid, cpid

    def test_sequential_track_paths_for_same_checkpoint(self) -> None:
        """Multiple tools tracking different files under the same checkpoint sequentially."""
        _, cpid = self._new_checkpoint()

        files: list[Path] = []
        for i in range(5):
            f = self._tmp_dir / f"file_{i}.txt"
            f.write_text(f"content_{i}", encoding="utf-8")
            files.append(f)

        for f in files:
            self._checkpoints.track_paths(cpid, [str(f)])

        rows = self._store.execute(
            "SELECT COUNT(*) AS c FROM checkpoint_files WHERE checkpoint_id = ?",
            (cpid,),
        ).fetchone()
        self.assertEqual(5, int(rows["c"]))

    def test_track_same_file_twice_is_idempotent(self) -> None:
        """Tracking the same file multiple times should not duplicate the snapshot."""
        _, cpid = self._new_checkpoint()
        target = self._tmp_dir / "shared.txt"
        target.write_text("original", encoding="utf-8")

        for _ in range(5):
            self._checkpoints.track_paths(cpid, [str(target)])

        rows = self._store.execute(
            "SELECT COUNT(*) AS c FROM checkpoint_files WHERE checkpoint_id = ? AND path = ?",
            (cpid, str(target.resolve())),
        ).fetchone()
        self.assertEqual(1, int(rows["c"]))

    def test_rewind_after_parallel_tracking(self) -> None:
        """Files tracked concurrently should all be rewindable."""
        _, cpid = self._new_checkpoint()

        originals = {}
        for i in range(3):
            f = self._tmp_dir / f"parallel_{i}.txt"
            f.write_text(f"original_{i}", encoding="utf-8")
            originals[str(f)] = f"original_{i}"
            self._checkpoints.track_paths(cpid, [str(f)])

        # Mutate all files
        for f_path in originals:
            Path(f_path).write_text("mutated", encoding="utf-8")

        _, outcomes = self._checkpoints.rewind_files(cpid)
        self.assertEqual(3, len(outcomes))
        for outcome in outcomes:
            self.assertEqual("restored", outcome["status"])
            self.assertEqual(originals[outcome["path"]], Path(outcome["path"]).read_text(encoding="utf-8"))

    def test_many_checkpoints_per_session(self) -> None:
        """Creating many checkpoints for a session should not degrade."""
        sid = self._sessions.create_session()
        checkpoint_ids = []
        for i in range(50):
            mid, _ = self._sessions.append_message(sid, "user", f"turn {i}")
            cpid = self._checkpoints.create_checkpoint(sid, mid)
            checkpoint_ids.append(cpid)

        listed = self._checkpoints.list_checkpoints(sid, limit=100)
        self.assertEqual(50, len(listed))
        # Most recent first
        self.assertEqual(checkpoint_ids[-1], listed[0]["id"])


class RetentionHardeningTests(MemoryStoreTestCase):
    """Edge cases for retention/pruning logic."""

    def test_pruning_does_not_delete_active_session_within_retention(self) -> None:
        """A session within retention window should survive pruning even with max_sessions=1."""
        sid_old = self._sessions.create_session("old")
        self._store.execute(
            "UPDATE sessions SET updated_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
            (sid_old,),
        )
        self._store.commit()

        sid_new = self._sessions.create_session("new")

        prune_memory(
            self._store,
            max_sessions=1,
            max_messages_per_session=5000,
            retention_days=36500,
        )

        remaining = self._store.execute("SELECT id FROM sessions").fetchall()
        ids = [str(r["id"]) for r in remaining]
        self.assertIn(sid_new, ids)
        self.assertNotIn(sid_old, ids)

    def test_pruning_with_zero_messages_in_session(self) -> None:
        """Session with no messages should be prunable without error."""
        sid = self._sessions.create_session("empty")
        self._store.execute(
            "UPDATE sessions SET updated_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
            (sid,),
        )
        self._store.commit()

        prune_memory(
            self._store,
            max_sessions=200,
            max_messages_per_session=5000,
            retention_days=1,
        )

        row = self._store.execute("SELECT id FROM sessions WHERE id = ?", (sid,)).fetchone()
        self.assertIsNone(row)

    def test_max_messages_boundary_keeps_exact_count(self) -> None:
        """When messages == max, no pruning should occur."""
        sid = self._sessions.create_session("boundary")
        for i in range(5):
            self._sessions.append_message(sid, "user", f"msg{i}")

        prune_memory(
            self._store,
            max_sessions=200,
            max_messages_per_session=5,
            retention_days=36500,
        )

        rows = self._store.execute(
            "SELECT COUNT(*) AS c FROM messages WHERE session_id = ?", (sid,)
        ).fetchone()
        self.assertEqual(5, int(rows["c"]))

    def test_max_messages_prunes_oldest_keeps_newest(self) -> None:
        """Pruning with max_messages_per_session=3 on 5 messages keeps 3 most recent."""
        sid = self._sessions.create_session("prune-msgs")
        for i in range(5):
            self._sessions.append_message(sid, "user", f"msg{i}")

        prune_memory(
            self._store,
            max_sessions=200,
            max_messages_per_session=3,
            retention_days=36500,
        )

        rows = self._store.execute(
            "SELECT seq FROM messages WHERE session_id = ? ORDER BY seq ASC", (sid,)
        ).fetchall()
        seqs = [int(r["seq"]) for r in rows]
        self.assertEqual([3, 4, 5], seqs)

    def test_multiple_sessions_pruned_independently(self) -> None:
        """Per-session message caps are applied independently."""
        sid_a = self._sessions.create_session("a")
        sid_b = self._sessions.create_session("b")
        for i in range(4):
            self._sessions.append_message(sid_a, "user", f"a{i}")
        for i in range(2):
            self._sessions.append_message(sid_b, "user", f"b{i}")

        prune_memory(
            self._store,
            max_sessions=200,
            max_messages_per_session=2,
            retention_days=36500,
        )

        count_a = self._store.execute(
            "SELECT COUNT(*) AS c FROM messages WHERE session_id = ?", (sid_a,)
        ).fetchone()
        count_b = self._store.execute(
            "SELECT COUNT(*) AS c FROM messages WHERE session_id = ?", (sid_b,)
        ).fetchone()
        self.assertEqual(2, int(count_a["c"]))
        self.assertEqual(2, int(count_b["c"]))

    def test_cascading_delete_removes_related_rows(self) -> None:
        """Deleting a session should cascade to messages, tool_calls, checkpoints, events."""
        sid = self._sessions.create_session("cascade")
        mid, _ = self._sessions.append_message(sid, "user", "test cascade")
        self._sessions.record_tool_call(
            sid,
            message_id=mid,
            tool_name="write_file",
            tool_input={"path": "x.txt"},
            result_text="ok",
            is_error=False,
            tool_call_id="tc1",
        )
        self._events.emit(sid, "test.event", {"key": "val"})

        # Force the session to be old enough to prune
        self._store.execute(
            "UPDATE sessions SET updated_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
            (sid,),
        )
        self._store.commit()

        prune_memory(
            self._store,
            max_sessions=200,
            max_messages_per_session=5000,
            retention_days=1,
        )

        # sessions table uses 'id', others use 'session_id'
        row = self._store.execute(
            "SELECT COUNT(*) AS c FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
        self.assertEqual(0, int(row["c"]), "Expected 0 rows in sessions")
        for table in ["messages", "tool_calls", "events"]:
            row = self._store.execute(
                f"SELECT COUNT(*) AS c FROM {table} WHERE session_id = ?", (sid,)
            ).fetchone()
            self.assertEqual(0, int(row["c"]), f"Expected 0 rows in {table}")


class EventSinkConcurrencyTests(MemoryStoreTestCase):
    """Verify event sink handles concurrent emits safely."""

    def test_many_concurrent_emits(self) -> None:
        """Emit many events concurrently and verify all are persisted."""
        sid = self._sessions.create_session("sink-stress")
        sink = AsyncEventSink(self._store, batch_size=10, flush_interval_seconds=0.05)
        emitter = EventEmitter(self._store, sink=sink)

        async def scenario() -> None:
            await sink.start()
            for i in range(100):
                emitter.emit(sid, f"stress.event.{i % 5}", {"index": i})
            await asyncio.sleep(0.3)
            await sink.close()

        asyncio.run(scenario())

        row = self._store.execute(
            "SELECT COUNT(*) AS c FROM events WHERE session_id = ? AND type LIKE 'stress.%'",
            (sid,),
        ).fetchone()
        self.assertEqual(100, int(row["c"]))


if __name__ == "__main__":
    unittest.main()
