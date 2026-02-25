from pathlib import Path

from micro_x_agent_loop.memory import CheckpointManager
from tests.memory.base import MemoryStoreTestCase


class TrackPathsTests(MemoryStoreTestCase):
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
        user_message_id, _ = self._sessions.append_message(sid, "user", "test")
        checkpoint_id = self._checkpoints.create_checkpoint(sid, user_message_id)
        return sid, checkpoint_id

    # ---- Multiple paths ---------------------------------------------------

    def test_track_multiple_paths(self) -> None:
        _, cp_id = self._new_checkpoint()
        file_a = self._tmp_dir / "a.txt"
        file_b = self._tmp_dir / "b.txt"
        file_a.write_text("aaa", encoding="utf-8")
        file_b.write_text("bbb", encoding="utf-8")

        tracked = self._checkpoints.track_paths(cp_id, [str(file_a), str(file_b)])
        self.assertEqual(2, len(tracked))

        # Mutate both files.
        file_a.write_text("aaa-changed", encoding="utf-8")
        file_b.write_text("bbb-changed", encoding="utf-8")

        _, outcomes = self._checkpoints.rewind_files(cp_id)
        statuses = {o["path"]: o["status"] for o in outcomes}
        self.assertEqual("restored", statuses[str(file_a.resolve())])
        self.assertEqual("restored", statuses[str(file_b.resolve())])
        self.assertEqual("aaa", file_a.read_text(encoding="utf-8"))
        self.assertEqual("bbb", file_b.read_text(encoding="utf-8"))

    # ---- Outside working directory silently skipped -----------------------

    def test_outside_workdir_silently_skipped(self) -> None:
        _, cp_id = self._new_checkpoint()
        outside = Path(__file__).resolve().parents[3] / "outside.txt"
        inside = self._tmp_dir / "inside.txt"
        inside.write_text("ok", encoding="utf-8")

        tracked = self._checkpoints.track_paths(cp_id, [str(outside), str(inside)])
        # Only the inside path should be tracked.
        self.assertEqual(1, len(tracked))
        self.assertEqual(str(inside.resolve()), tracked[0])

    # ---- Empty list -------------------------------------------------------

    def test_empty_list_returns_empty(self) -> None:
        _, cp_id = self._new_checkpoint()
        tracked = self._checkpoints.track_paths(cp_id, [])
        self.assertEqual([], tracked)

    # ---- Blank strings ----------------------------------------------------

    def test_blank_strings_skipped(self) -> None:
        _, cp_id = self._new_checkpoint()
        tracked = self._checkpoints.track_paths(cp_id, ["", "   ", "  \t  "])
        self.assertEqual([], tracked)

    # ---- Rewind after track_paths -----------------------------------------

    def test_rewind_removes_new_file_tracked_via_track_paths(self) -> None:
        _, cp_id = self._new_checkpoint()
        target = self._tmp_dir / "will-be-created.txt"

        self._checkpoints.track_paths(cp_id, [str(target)])
        target.write_text("created later", encoding="utf-8")

        _, outcomes = self._checkpoints.rewind_files(cp_id)
        self.assertFalse(target.exists())
        self.assertEqual("removed", outcomes[0]["status"])

    # ---- maybe_track_tool_input still works (backward compat) -------------

    def test_maybe_track_tool_input_delegates_to_track_paths(self) -> None:
        _, cp_id = self._new_checkpoint()
        target = self._tmp_dir / "compat.txt"
        target.write_text("original", encoding="utf-8")

        result = self._checkpoints.maybe_track_tool_input(cp_id, {"path": str(target)})
        self.assertEqual(1, len(result))

        target.write_text("changed", encoding="utf-8")
        _, outcomes = self._checkpoints.rewind_files(cp_id)
        self.assertEqual("restored", outcomes[0]["status"])
        self.assertEqual("original", target.read_text(encoding="utf-8"))
