"""Tests for routing_feedback module."""

from __future__ import annotations

import os
import tempfile
import time
import unittest

from micro_x_agent_loop.routing_feedback import RoutingFeedbackStore, RoutingOutcome


class RoutingFeedbackStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._tmpdir, "test_routing.db")
        self._store = RoutingFeedbackStore(self._db_path)

    def tearDown(self) -> None:
        self._store.close()

    def _make_outcome(self, **kwargs) -> RoutingOutcome:
        defaults = {
            "session_id": "sess-1",
            "turn_number": 1,
            "task_type": "code_generation",
            "provider": "anthropic",
            "model": "claude-sonnet",
            "cost_usd": 0.005,
            "latency_ms": 1200.0,
            "stage": "rules",
            "confidence": 0.85,
            "quality_signal": 0,
            "timestamp": time.time(),
        }
        defaults.update(kwargs)
        return RoutingOutcome(**defaults)

    def test_record_and_get_recent(self) -> None:
        self._store.record(self._make_outcome(turn_number=1))
        self._store.record(self._make_outcome(turn_number=2))
        outcomes = self._store.get_recent_outcomes(10)
        self.assertEqual(len(outcomes), 2)

    def test_task_type_stats(self) -> None:
        self._store.record(self._make_outcome(task_type="trivial", cost_usd=0.001))
        self._store.record(self._make_outcome(task_type="trivial", cost_usd=0.002))
        self._store.record(self._make_outcome(task_type="analysis", cost_usd=0.010))
        stats = self._store.get_task_type_stats()
        self.assertEqual(len(stats), 2)
        trivial = next(s for s in stats if s["task_type"] == "trivial")
        self.assertEqual(trivial["total"], 2)
        self.assertAlmostEqual(trivial["avg_cost"], 0.0015, places=4)

    def test_provider_stats(self) -> None:
        self._store.record(self._make_outcome(provider="anthropic"))
        self._store.record(self._make_outcome(provider="openai"))
        stats = self._store.get_provider_stats()
        self.assertEqual(len(stats), 2)

    def test_stage_stats(self) -> None:
        self._store.record(self._make_outcome(stage="rules"))
        self._store.record(self._make_outcome(stage="rules"))
        self._store.record(self._make_outcome(stage="keywords"))
        stats = self._store.get_stage_stats()
        rules = next(s for s in stats if s["stage"] == "rules")
        self.assertEqual(rules["total"], 2)
        self.assertAlmostEqual(rules["percentage"], 66.7, places=1)

    def test_update_quality_signal(self) -> None:
        self._store.record(self._make_outcome(turn_number=3))
        self._store.update_quality_signal("sess-1", 3, -1)
        outcomes = self._store.get_recent_outcomes(1)
        self.assertEqual(outcomes[0]["quality_signal"], -1)

    def test_adaptive_thresholds_empty(self) -> None:
        thresholds = self._store.get_adaptive_thresholds()
        self.assertEqual(thresholds, {})

    def test_adaptive_thresholds_with_data(self) -> None:
        for i in range(10):
            signal = -1 if i < 3 else 0  # 30% error rate
            self._store.record(self._make_outcome(
                turn_number=i,
                task_type="trivial",
                quality_signal=signal,
            ))
        thresholds = self._store.get_adaptive_thresholds()
        self.assertIn("trivial", thresholds)
        # 30% error → threshold = 0.6 + 0.3 * 0.5 = 0.75
        self.assertAlmostEqual(thresholds["trivial"], 0.75, places=1)

    def test_close_and_reopen(self) -> None:
        self._store.record(self._make_outcome())
        self._store.close()
        store2 = RoutingFeedbackStore(self._db_path)
        outcomes = store2.get_recent_outcomes(10)
        self.assertEqual(len(outcomes), 1)
        store2.close()
