"""Phase 5 — rolling-window observability alerting."""

from __future__ import annotations

import os
import tempfile
import unittest

from micro_x_agent_loop.alerting import Alert, AlertRule, build_alert_subscriber, evaluate_alerts
from micro_x_agent_loop.memory.events import EventEmitter
from micro_x_agent_loop.memory.store import MemoryStore


def _rule(metric: str, threshold: float, window: int = 50, channel: str = "log") -> AlertRule:
    r = AlertRule.from_config({"metric": metric, "threshold": threshold, "window": window, "channel": channel})
    assert r is not None
    return r


class EvaluateAlertsTests(unittest.TestCase):
    def test_cost_window_above_fires(self) -> None:
        events = [{"type": "metric.api_call", "payload": {"estimated_cost_usd": 0.5}} for _ in range(3)]
        fired = evaluate_alerts(events, [_rule("cost_window", 1.0)])
        self.assertEqual(len(fired), 1)
        self.assertAlmostEqual(fired[0].value, 1.5)

    def test_cost_window_under_threshold_silent(self) -> None:
        events = [{"type": "metric.api_call", "payload": {"estimated_cost_usd": 0.1}}]
        self.assertEqual(evaluate_alerts(events, [_rule("cost_window", 1.0)]), [])

    def test_error_rate(self) -> None:
        events = [
            {"type": "metric.api_call", "payload": {}},
            {"type": "metric.api_call_error", "payload": {}},
        ]
        fired = evaluate_alerts(events, [_rule("error_rate", 0.4)])
        self.assertEqual(len(fired), 1)
        self.assertAlmostEqual(fired[0].value, 0.5)

    def test_avg_confidence_below_fires(self) -> None:
        events = [
            {"type": "routing.decision", "payload": {"confidence": 0.3}},
            {"type": "routing.decision", "payload": {"confidence": 0.5}},
        ]
        fired = evaluate_alerts(events, [_rule("avg_confidence", 0.6)])
        self.assertEqual(len(fired), 1)
        self.assertAlmostEqual(fired[0].value, 0.4)

    def test_cache_hit_rate_below_fires(self) -> None:
        events = [{"type": "metric.api_call", "payload": {"input_tokens": 900, "cache_read_input_tokens": 100}}]
        fired = evaluate_alerts(events, [_rule("cache_hit_rate", 0.5)])
        self.assertEqual(len(fired), 1)  # 100/1000 = 0.1 < 0.5

    def test_window_limits_scope(self) -> None:
        events = [{"type": "metric.api_call", "payload": {"estimated_cost_usd": 1.0}} for _ in range(10)]
        # window=2 → only last 2 counted → 2.0
        fired = evaluate_alerts(events, [_rule("cost_window", 1.5, window=2)])
        self.assertAlmostEqual(fired[0].value, 2.0)

    def test_unknown_metric_rule_dropped(self) -> None:
        self.assertIsNone(AlertRule.from_config({"metric": "bogus", "threshold": 1}))


class AlertSubscriberTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.store = MemoryStore(os.path.join(self.tmp, "m.db"))
        self.emitter = EventEmitter(self.store)
        # a session row is needed for FK on events
        self.store.execute(
            "INSERT INTO sessions (id, created_at, updated_at, status, model, metadata_json) "
            "VALUES ('s1','t','t','active','m','{}')"
        )
        self.store.commit()

    def tearDown(self) -> None:
        self.store.close()

    def test_subscriber_fires_once_edge_triggered(self) -> None:
        fired: list[Alert] = []
        sub = build_alert_subscriber(
            [{"metric": "cost_window", "threshold": 0.3, "window": 100}],
            self.store,
            notifier=fired.append,
        )
        assert sub is not None
        # Two expensive calls persisted, then evaluate via the subscriber each time.
        for _ in range(2):
            self.emitter.emit("s1", "metric.api_call", {"session_id": "s1", "estimated_cost_usd": 0.5})
            sub("metric.api_call", {"session_id": "s1"})
        # Breach is sustained across both, but edge-triggered → exactly one alert.
        self.assertEqual(len(fired), 1)

    def test_no_rules_returns_none(self) -> None:
        self.assertIsNone(build_alert_subscriber([], self.store))


if __name__ == "__main__":
    unittest.main()
