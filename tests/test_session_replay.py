"""Phase 2 — session step-through reconstruction (/replay data source)."""

from __future__ import annotations

import os
import tempfile
import unittest

from micro_x_agent_loop.memory.events import EventEmitter
from micro_x_agent_loop.memory.session_manager import SessionManager
from micro_x_agent_loop.memory.store import MemoryStore
from micro_x_agent_loop.observability import ObservabilityEmitter
from micro_x_agent_loop.session_replay import reconstruct_session


class _Facade:
    """Minimal event-log facade for the ObservabilityEmitter."""

    def __init__(self, sm: SessionManager, session_id: str, emitter: EventEmitter) -> None:
        self._sm = sm
        self._sid = session_id
        self._emitter = emitter

    def emit_event(self, event_type: str, payload: dict) -> None:
        self._emitter.emit(self._sid, event_type, payload)


class SessionReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.store = MemoryStore(os.path.join(self.tmp, "memory.db"))
        self.emitter = EventEmitter(self.store)
        self.sm = SessionManager(self.store, "test-model", self.emitter)
        self.session_id = self.sm.create_session("replay-test")
        self.obs = ObservabilityEmitter(_Facade(self.sm, self.session_id, self.emitter))

    def tearDown(self) -> None:
        self.store.close()

    def _seed_one_turn(self) -> None:
        self.obs.emit(
            "session.config",
            {
                "session_id": self.session_id,
                "code_sha": "abc123-dirty",
                "config_hash": "deadbeef",
                "config": {"model": "m"},
            },
            turn_number=1,
        )
        self.obs.emit(
            "mode.analyzed",
            {"signals": [{"name": "batch", "strength": "strong"}], "stage1_recommendation": "COMPILED",
             "stage2_recommendation": None, "stage2_reasoning": "", "user_choice": "PROMPT"},
            turn_number=1,
        )
        self.obs.emit(
            "routing.decision",
            {"task_type": "code_generation", "stage": "rules", "confidence": 0.95, "policy_name": "code_generation",
             "provider": "anthropic", "model": "claude", "confidence_gate_triggered": False},
            turn_number=1,
        )
        sha = self.sm.persist_system_prompt("you are a helpful agent prompt")
        self.obs.emit(
            "llm.call",
            {"call_type": "main", "effective_provider": "anthropic", "effective_model": "claude",
             "temperature": 0.0, "max_tokens": 4096, "message_count": 3, "tool_names": ["web_fetch", "echo"],
             "system_prompt_sha256": sha, "system_prompt_chars": 29},
            turn_number=1,
            iteration=0,
        )
        self.obs.emit(
            "metric.api_call",
            {"input_tokens": 1200, "output_tokens": 300, "estimated_cost_usd": 0.0042,
             "duration_ms": 1100, "stop_reason": "tool_use"},
            turn_number=1,
        )
        self.sm.record_tool_call(
            self.session_id, message_id=None, tool_name="web_fetch", tool_input={"url": "http://x"},
            result_text="short result", is_error=False, was_truncated=True, original_chars=50000,
        )

    def test_reconstruct_renders_turn_timeline(self) -> None:
        self._seed_one_turn()
        lines = reconstruct_session(self.store, self.session_id)
        text = "\n".join(lines)

        self.assertIn(f"Session {self.session_id}", text)
        self.assertIn("── Turn 1 ──", text)
        self.assertIn("code_sha=abc123-dirty", text)
        self.assertIn("[mode]", text)
        self.assertIn("choice=PROMPT", text)
        self.assertIn("[routing] task=code_generation", text)
        self.assertIn("[llm.call] main → anthropic/claude", text)
        self.assertIn("tools=[web_fetch,echo]", text)
        self.assertIn("[api]", text)
        self.assertIn("$0.0042", text)
        self.assertIn("[tool] web_fetch", text)
        self.assertIn("truncated 50000→12 chars", text)

    def test_confidence_gate_flag_rendered(self) -> None:
        self.obs.emit(
            "routing.decision",
            {"task_type": "trivial", "stage": "rules", "confidence": 0.3, "policy_name": "trivial",
             "provider": "anthropic", "model": "main", "confidence_gate_triggered": True},
            turn_number=1,
        )
        lines = reconstruct_session(self.store, self.session_id)
        self.assertIn("confidence-gate", "\n".join(lines))

    def test_unknown_session_raises(self) -> None:
        with self.assertRaises(ValueError):
            reconstruct_session(self.store, "does-not-exist")


if __name__ == "__main__":
    unittest.main()
