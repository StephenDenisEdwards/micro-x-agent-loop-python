import unittest
from typing import Any

from micro_x_agent_loop.memory.facade import ActiveMemoryFacade, NullMemoryFacade
from tests.fakes import FakeEventEmitter, FakeTool

# ---------------------------------------------------------------------------
# Minimal session/checkpoint manager stubs
# ---------------------------------------------------------------------------


class _SessionManagerStub:
    def __init__(self) -> None:
        self.appended: list[tuple] = []
        self.tool_calls: list[dict] = []
        self._messages: list[dict] = [{"role": "user", "content": "hello"}]

    def append_message(self, session_id: str, role: str, content: str | list[dict]) -> tuple[str, int]:
        self.appended.append((session_id, role, content))
        return f"m{len(self.appended)}", len(self.appended)

    def record_tool_call(self, session_id: str, **kwargs: Any) -> str:
        self.tool_calls.append({"session_id": session_id, **kwargs})
        return "tc1"

    def load_messages(self, session_id: str) -> list[dict]:
        return list(self._messages)


class _CheckpointManagerStub:
    enabled = True
    write_tools_only = False

    def __init__(self) -> None:
        self.created: list[tuple] = []
        self.tracked: list[tuple] = []

    def create_checkpoint(self, session_id: str, user_message_id: str, *, scope: dict | None = None) -> str:
        self.created.append((session_id, user_message_id, scope))
        return "cp-1"

    def track_paths(self, checkpoint_id: str, paths: list[str]) -> list[str]:
        self.tracked.append((checkpoint_id, paths))
        return paths

    def maybe_track_tool_input(self, checkpoint_id: str, tool_input: dict) -> list[str]:
        return []


# ---------------------------------------------------------------------------
# NullMemoryFacade tests
# ---------------------------------------------------------------------------


class NullMemoryFacadeTests(unittest.TestCase):
    def test_append_message_returns_none(self) -> None:
        facade = NullMemoryFacade()
        self.assertIsNone(facade.append_message("user", "hello"))

    def test_ensure_checkpoint_returns_none(self) -> None:
        facade = NullMemoryFacade()
        result = facade.ensure_checkpoint_for_turn(
            [{"name": "read_file"}],
            user_message_id="m1",
            user_message_text="hi",
            current_checkpoint_id=None,
        )
        self.assertIsNone(result)

    def test_maybe_track_mutation_is_noop(self) -> None:
        facade = NullMemoryFacade()
        tool = FakeTool(is_mutating=True)
        facade.maybe_track_mutation("noop", tool, {}, "cp1")

    def test_record_tool_call_is_noop(self) -> None:
        facade = NullMemoryFacade()
        facade.record_tool_call(
            tool_call_id="tc1",
            tool_name="noop",
            tool_input={},
            result_text="ok",
            is_error=False,
            message_id=None,
        )

    def test_emit_events_are_noop(self) -> None:
        facade = NullMemoryFacade()
        facade.emit_tool_started("t1", "noop")
        facade.emit_tool_completed("t1", "noop", False)

    def test_load_messages_returns_empty(self) -> None:
        facade = NullMemoryFacade()
        self.assertEqual([], facade.load_messages("s1"))

    def test_properties(self) -> None:
        facade = NullMemoryFacade()
        self.assertIsNone(facade.session_manager)
        self.assertIsNone(facade.checkpoint_manager)
        self.assertIsNone(facade.active_session_id)
        facade.active_session_id = "s1"
        self.assertEqual("s1", facade.active_session_id)


# ---------------------------------------------------------------------------
# ActiveMemoryFacade tests
# ---------------------------------------------------------------------------


class ActiveMemoryFacadeTests(unittest.TestCase):
    def _make_facade(
        self,
        session_manager=None,
        checkpoint_manager=None,
        event_emitter=None,
        session_id="s1",
    ) -> ActiveMemoryFacade:
        return ActiveMemoryFacade(
            session_manager=session_manager or _SessionManagerStub(),
            checkpoint_manager=checkpoint_manager,
            event_emitter=event_emitter,
            active_session_id=session_id,
        )

    def test_append_message_delegates_to_session_manager(self) -> None:
        sm = _SessionManagerStub()
        facade = self._make_facade(session_manager=sm)
        mid = facade.append_message("user", "hello")
        self.assertEqual("m1", mid)
        self.assertEqual(1, len(sm.appended))
        self.assertEqual(("s1", "user", "hello"), sm.appended[0])

    def test_append_message_returns_none_when_no_session_id(self) -> None:
        sm = _SessionManagerStub()
        facade = self._make_facade(session_manager=sm, session_id=None)
        self.assertIsNone(facade.append_message("user", "hello"))

    def test_ensure_checkpoint_creates_checkpoint(self) -> None:
        cm = _CheckpointManagerStub()
        facade = self._make_facade(checkpoint_manager=cm)
        result = facade.ensure_checkpoint_for_turn(
            [{"name": "write_file"}],
            user_message_id="m1",
            user_message_text="do it",
            current_checkpoint_id=None,
        )
        self.assertEqual("cp-1", result)
        self.assertEqual(1, len(cm.created))

    def test_ensure_checkpoint_skips_when_already_exists(self) -> None:
        cm = _CheckpointManagerStub()
        facade = self._make_facade(checkpoint_manager=cm)
        result = facade.ensure_checkpoint_for_turn(
            [{"name": "write_file"}],
            user_message_id="m1",
            user_message_text="do it",
            current_checkpoint_id="cp-existing",
        )
        self.assertIsNone(result)
        self.assertEqual(0, len(cm.created))

    def test_maybe_track_mutation_calls_track_paths(self) -> None:
        cm = _CheckpointManagerStub()
        facade = self._make_facade(checkpoint_manager=cm)
        tool = FakeTool(is_mutating=True, touched_paths=["/a.txt"])
        facade.maybe_track_mutation("write_file", tool, {"path": "/a.txt"}, "cp-1")
        self.assertEqual(1, len(cm.tracked))
        self.assertEqual(("cp-1", ["/a.txt"]), cm.tracked[0])

    def test_maybe_track_mutation_skips_when_no_checkpoint(self) -> None:
        cm = _CheckpointManagerStub()
        facade = self._make_facade(checkpoint_manager=cm)
        tool = FakeTool(is_mutating=True, touched_paths=["/a.txt"])
        facade.maybe_track_mutation("write_file", tool, {}, None)
        self.assertEqual(0, len(cm.tracked))

    def test_record_tool_call_delegates(self) -> None:
        sm = _SessionManagerStub()
        facade = self._make_facade(session_manager=sm)
        facade.record_tool_call(
            tool_call_id="tc1",
            tool_name="write_file",
            tool_input={"path": "a.txt"},
            result_text="ok",
            is_error=False,
            message_id="m1",
        )
        self.assertEqual(1, len(sm.tool_calls))

    def test_emit_tool_started_delegates_to_emitter(self) -> None:
        emitter = FakeEventEmitter()
        facade = self._make_facade(event_emitter=emitter)
        facade.emit_tool_started("t1", "write_file")
        self.assertEqual(1, len(emitter.events))

    def test_emit_tool_completed_delegates_to_emitter(self) -> None:
        emitter = FakeEventEmitter()
        facade = self._make_facade(event_emitter=emitter)
        facade.emit_tool_completed("t1", "write_file", False)
        self.assertEqual(1, len(emitter.events))

    def test_emit_skipped_when_no_emitter(self) -> None:
        facade = self._make_facade(event_emitter=None)
        facade.emit_tool_started("t1", "write_file")
        facade.emit_tool_completed("t1", "write_file", False)

    def test_load_messages_delegates(self) -> None:
        sm = _SessionManagerStub()
        facade = self._make_facade(session_manager=sm)
        msgs = facade.load_messages("s1")
        self.assertEqual(1, len(msgs))
        self.assertEqual("user", msgs[0]["role"])

    def test_active_session_id_property(self) -> None:
        facade = self._make_facade(session_id="s1")
        self.assertEqual("s1", facade.active_session_id)
        facade.active_session_id = "s2"
        self.assertEqual("s2", facade.active_session_id)

    def test_properties(self) -> None:
        sm = _SessionManagerStub()
        cm = _CheckpointManagerStub()
        facade = self._make_facade(session_manager=sm, checkpoint_manager=cm)
        self.assertIs(sm, facade.session_manager)
        self.assertIs(cm, facade.checkpoint_manager)


if __name__ == "__main__":
    unittest.main()
