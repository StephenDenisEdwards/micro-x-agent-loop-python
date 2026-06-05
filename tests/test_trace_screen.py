"""Trace browser — structured session model + TraceScreen pilot smoke."""

from __future__ import annotations

import os
import tempfile
import unittest

from micro_x_agent_loop.memory.events import EventEmitter
from micro_x_agent_loop.memory.session_manager import SessionManager
from micro_x_agent_loop.memory.store import MemoryStore
from micro_x_agent_loop.observability import ObservabilityEmitter
from micro_x_agent_loop.session_replay import build_session_model


class _F:
    def __init__(self, emitter: EventEmitter, sid: str) -> None:
        self._emitter, self._sid = emitter, sid

    def emit_event(self, event_type: str, payload: dict) -> None:
        self._emitter.emit(self._sid, event_type, payload)


def _seed(store: MemoryStore) -> tuple[str, SessionManager]:
    emitter = EventEmitter(store)
    sm = SessionManager(store, "m", emitter, verbatim_capture=True)
    sid = sm.create_session("trace-test")
    obs = ObservabilityEmitter(_F(emitter, sid))
    obs.emit(
        "session.config",
        {"session_id": sid, "code_sha": "abc-dirty", "config_hash": "h1", "config": {"model": "m"}},
        turn_number=1,
    )
    obs.emit(
        "mode.analyzed",
        {"signals": [], "stage1_recommendation": "PROMPT", "stage2_recommendation": None,
         "stage2_reasoning": "", "user_choice": None},
        turn_number=1,
    )
    obs.emit(
        "routing.decision",
        {"session_id": sid, "turn_number": 1, "task_type": "code_generation", "stage": "rules",
         "confidence": 0.9, "policy_name": "code_generation", "provider": "anthropic", "model": "claude"},
        turn_number=1,
    )
    sha = sm.persist_system_prompt("YOU ARE A HELPFUL AGENT")
    rid = sm.persist_llm_request(
        sid, turn_number=1, iteration=0, system_prompt_sha256=sha,
        messages=[{"role": "user", "content": "exact user msg"}], tools=[{"name": "web_fetch"}],
    )
    obs.emit(
        "llm.call",
        {"session_id": sid, "turn_number": 1, "call_type": "main", "effective_provider": "anthropic",
         "effective_model": "claude", "system_prompt_sha256": sha, "tool_names": ["web_fetch"], "request_id": rid},
        turn_number=1, iteration=0,
    )
    obs.emit(
        "metric.api_call",
        {"session_id": sid, "turn_number": 1, "model": "claude", "input_tokens": 100, "output_tokens": 50,
         "estimated_cost_usd": 0.004, "duration_ms": 1100},
        turn_number=1,
    )
    sm.record_tool_call(sid, message_id=None, tool_name="web_fetch", tool_input={"url": "x"},
                        result_text="result body", is_error=False)
    return sid, sm


class BuildSessionModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.store = MemoryStore(os.path.join(self.tmp, "m.db"))
        self.sid, _ = _seed(self.store)

    def tearDown(self) -> None:
        self.store.close()

    def test_model_has_turns_and_event_kinds(self) -> None:
        model = build_session_model(self.store, self.sid)
        self.assertEqual(model.session_id, self.sid)
        all_events = [e for turn in model.turns for e in turn.events]
        kinds = {e.kind for e in all_events}
        for expected in ("config", "mode", "routing", "llm_call", "api", "tool"):
            self.assertIn(expected, kinds)

    def test_llm_call_detail_contains_verbatim(self) -> None:
        model = build_session_model(self.store, self.sid)
        llm = next(e for turn in model.turns for e in turn.events if e.kind == "llm_call")
        self.assertIn("YOU ARE A HELPFUL AGENT", llm.detail_md)  # full system prompt
        self.assertIn("exact user msg", llm.detail_md)            # verbatim messages
        self.assertIn("web_fetch", llm.detail_md)                 # verbatim tool schema
        self.assertIn("```json", llm.detail_md)                   # fenced for the panel

    def test_tool_detail_has_input_and_result(self) -> None:
        model = build_session_model(self.store, self.sid)
        tool = next(e for turn in model.turns for e in turn.events if e.kind == "tool")
        self.assertIn("Input", tool.detail_md)
        self.assertIn("result body", tool.detail_md)

    def test_unknown_session_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_session_model(self.store, "nope")


try:
    import textual  # noqa: F401
    _HAS_TEXTUAL = True
except ImportError:
    _HAS_TEXTUAL = False


@unittest.skipUnless(_HAS_TEXTUAL, "textual extra not installed")
class TraceScreenPilotTests(unittest.IsolatedAsyncioTestCase):
    async def test_screen_populates_tree_and_shows_detail(self) -> None:
        from textual.app import App
        from textual.widgets import Markdown, Tree

        from micro_x_agent_loop.tui.screens.trace_screen import TraceScreen

        tmp = tempfile.mkdtemp()
        store = MemoryStore(os.path.join(tmp, "m.db"))
        sid, _ = _seed(store)

        screen = TraceScreen(store, [(sid, "trace-test")], focus_session_id=sid)

        class _Host(App):
            def on_mount(self) -> None:
                self.push_screen(screen)

        app = _Host()
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                tree = screen.query_one("#trace-tree", Tree)
                # focus session was auto-expanded → turn + event nodes exist
                session_node = tree.root.children[0]
                self.assertTrue(session_node.children, "session should have populated turn nodes")
                event_nodes = [c for turn in session_node.children for c in turn.children]
                self.assertTrue(event_nodes, "turns should have event leaves")
                # selecting an event node updates the detail markdown
                target = next(n for n in event_nodes if (n.data or {}).get("type") == "event")
                tree.select_node(target)
                await pilot.pause()
                detail = screen.query_one("#trace-detail", Markdown)
                self.assertIsNotNone(detail)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
