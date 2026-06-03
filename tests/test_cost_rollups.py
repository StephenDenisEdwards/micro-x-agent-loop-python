"""Phase 7 — cost rollups + sampling policy."""

from __future__ import annotations

import os
import tempfile
import unittest

from micro_x_agent_loop.cost_rollups import compute_cost_rollups, should_retain_full
from micro_x_agent_loop.memory.events import EventEmitter
from micro_x_agent_loop.memory.session_manager import SessionManager
from micro_x_agent_loop.memory.store import MemoryStore
from micro_x_agent_loop.observability import ObservabilityEmitter


class _F:
    def __init__(self, emitter: EventEmitter, sid: str) -> None:
        self._emitter = emitter
        self._sid = sid

    def emit_event(self, event_type: str, payload: dict) -> None:
        self._emitter.emit(self._sid, event_type, payload)


class CostRollupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.store = MemoryStore(os.path.join(self.tmp, "m.db"))
        self.emitter = EventEmitter(self.store)
        self.sm = SessionManager(self.store, "m", self.emitter)
        self.sid = self.sm.create_session("rollup")
        self.store.execute("UPDATE sessions SET user_id = 'alice' WHERE id = ?", (self.sid,))
        self.store.commit()
        self.obs = ObservabilityEmitter(_F(self.emitter, self.sid))

    def tearDown(self) -> None:
        self.store.close()

    def _api(self, turn: int, cost: float, *, provider: str = "anthropic", model: str = "claude") -> None:
        self.obs.emit(
            "metric.api_call",
            {
                "session_id": self.sid, "turn_number": turn, "provider": provider, "model": model,
                "input_tokens": 100, "output_tokens": 50, "estimated_cost_usd": cost,
            },
            turn_number=turn,
        )

    def test_rollup_aggregates_by_key_with_user_and_task(self) -> None:
        self.obs.emit(
            "routing.decision",
            {"session_id": self.sid, "turn_number": 1, "task_type": "code_generation"},
            turn_number=1,
        )
        self._api(1, 0.01)
        self._api(1, 0.02)  # same turn/task -> aggregated
        self._api(2, 0.03)  # turn 2, no routing -> task_type ""

        rows = compute_cost_rollups(self.store)
        by_task = {r.task_type: r for r in rows}
        self.assertIn("code_generation", by_task)
        cg = by_task["code_generation"]
        self.assertEqual(cg.user_id, "alice")
        self.assertEqual(cg.calls, 2)
        self.assertAlmostEqual(cg.cost_usd, 0.03)
        self.assertEqual(cg.input_tokens, 200)
        # turn-2 call with no routing decision rolls up under empty task_type
        self.assertIn("", by_task)
        self.assertAlmostEqual(by_task[""].cost_usd, 0.03)

    def test_rollup_persisted_to_table(self) -> None:
        self._api(1, 0.05)
        compute_cost_rollups(self.store)
        row = next(iter(self.store.execute("SELECT user_id, cost_usd FROM cost_rollups")))
        self.assertEqual(row["user_id"], "alice")
        self.assertAlmostEqual(row["cost_usd"], 0.05)


class SamplingPolicyTests(unittest.TestCase):
    def test_errors_always_retained(self) -> None:
        self.assertTrue(should_retain_full(0.0, had_error=True))

    def test_high_cost_retained(self) -> None:
        self.assertTrue(should_retain_full(0.5, had_error=False))

    def test_low_cost_success_eligible_for_downsample(self) -> None:
        self.assertFalse(should_retain_full(0.001, had_error=False, low_cost_threshold=0.01))


if __name__ == "__main__":
    unittest.main()
