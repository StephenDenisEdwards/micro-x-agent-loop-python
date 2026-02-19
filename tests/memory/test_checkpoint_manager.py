from pathlib import Path

from micro_x_agent_loop.memory import CheckpointManager
from tests.memory.base import MemoryStoreTestCase


class CheckpointManagerTests(MemoryStoreTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._checkpoints = CheckpointManager(
            self._store,
            self._events,
            working_directory=str(self._tmp_dir),
            enabled=True,
            write_tools_only=True,
        )

    def _new_checkpoint(self) -> tuple[str, str]:
        sid = self._sessions.create_session()
        user_message_id, _ = self._sessions.append_message(sid, "user", "checkpoint test")
        checkpoint_id = self._checkpoints.create_checkpoint(sid, user_message_id)
        return sid, checkpoint_id

    def test_rewind_restores_previous_file_contents(self) -> None:
        _, checkpoint_id = self._new_checkpoint()
        target = self._tmp_dir / "notes.txt"
        target.write_text("before", encoding="utf-8")

        self._checkpoints.maybe_track_tool_input(checkpoint_id, {"path": str(target)})
        target.write_text("after", encoding="utf-8")

        _, outcomes = self._checkpoints.rewind_files(checkpoint_id)

        self.assertEqual("before", target.read_text(encoding="utf-8"))
        self.assertEqual("restored", outcomes[0]["status"])

    def test_rewind_removes_new_file_created_after_checkpoint(self) -> None:
        _, checkpoint_id = self._new_checkpoint()
        target = self._tmp_dir / "created-later.txt"

        self._checkpoints.maybe_track_tool_input(checkpoint_id, {"path": str(target)})
        target.write_text("new file", encoding="utf-8")

        _, outcomes = self._checkpoints.rewind_files(checkpoint_id)

        self.assertFalse(target.exists())
        self.assertEqual("removed", outcomes[0]["status"])

    def test_tracking_outside_working_directory_is_blocked(self) -> None:
        _, checkpoint_id = self._new_checkpoint()
        outside = Path(__file__).resolve().parents[3] / "outside.txt"
        with self.assertRaises(ValueError):
            self._checkpoints.maybe_track_tool_input(checkpoint_id, {"path": str(outside)})
