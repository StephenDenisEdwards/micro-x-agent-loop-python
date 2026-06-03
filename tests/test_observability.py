"""Tests for the ObservabilityEmitter seam (ADR-026 / PLAN-observability Phase 0)."""

from __future__ import annotations

import os
import tempfile
import unittest

from micro_x_agent_loop.observability import ObservabilityEmitter
from micro_x_agent_loop.routing_feedback import RoutingFeedbackStore, make_routing_outcome_subscriber


class _FakeEventLog:
    """Stand-in for the memory facade: records every persisted (type, payload)."""

    def __init__(self) -> None:
        self.persisted: list[tuple[str, dict]] = []

    def emit_event(self, event_type: str, payload: dict) -> None:
        self.persisted.append((event_type, payload))


class _NullEventLog:
    """Memory-disabled stand-in: persistence is a no-op (like NullMemoryFacade)."""

    def emit_event(self, event_type: str, payload: dict) -> None:
        return


class ObservabilityEmitterTests(unittest.TestCase):
    def test_emit_persists_once_and_fans_out(self) -> None:
        log = _FakeEventLog()
        emitter = ObservabilityEmitter(log)
        seen: list[tuple[str, dict]] = []
        emitter.subscribe(lambda t, p: seen.append((t, p)))

        emitter.emit("metric.api_call", {"model": "x"}, turn_number=3)

        # Persisted exactly once to the event log (source of truth).
        self.assertEqual(len(log.persisted), 1)
        self.assertEqual(log.persisted[0][0], "metric.api_call")
        # Same enriched payload fanned out to the subscriber.
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], "metric.api_call")
        self.assertIs(seen[0][1], log.persisted[0][1])

    def test_meta_correlation_tuple(self) -> None:
        emitter = ObservabilityEmitter(_FakeEventLog())
        first = emitter.emit("a", {}, turn_number=1, iteration=2)
        second = emitter.emit("b", {}, turn_number=1)

        self.assertEqual(first["_meta"], {"turn": 1, "iter": 2, "seq": 1})
        # seq is monotonic; iter defaults to 0.
        self.assertEqual(second["_meta"], {"turn": 1, "iter": 0, "seq": 2})

    def test_original_payload_preserved(self) -> None:
        emitter = ObservabilityEmitter(_FakeEventLog())
        enriched = emitter.emit("metric.api_call", {"type": "api_call", "cost": 0.01}, turn_number=0)
        self.assertEqual(enriched["type"], "api_call")
        self.assertEqual(enriched["cost"], 0.01)
        self.assertIn("_meta", enriched)

    def test_memory_off_still_fans_out(self) -> None:
        """metrics.jsonl must keep working when memory is disabled."""
        emitter = ObservabilityEmitter(_NullEventLog())
        seen: list[str] = []
        emitter.subscribe(lambda t, p: seen.append(t))
        emitter.emit("metric.api_call", {}, turn_number=0)
        self.assertEqual(seen, ["metric.api_call"])

    def test_subscriber_exception_is_isolated(self) -> None:
        log = _FakeEventLog()
        emitter = ObservabilityEmitter(log)
        good_seen: list[str] = []

        def _boom(t: str, p: dict) -> None:
            raise RuntimeError("subscriber blew up")

        emitter.subscribe(_boom)
        emitter.subscribe(lambda t, p: good_seen.append(t))

        # Must not raise; persist and the healthy subscriber still run.
        emitter.emit("metric.api_call", {}, turn_number=0)
        self.assertEqual(len(log.persisted), 1)
        self.assertEqual(good_seen, ["metric.api_call"])


class RoutingProjectionSubscriberTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._tmpdir, "routing.db")
        self._store = RoutingFeedbackStore(self._db_path)

    def tearDown(self) -> None:
        self._store.close()

    def test_routing_decision_projected_to_store(self) -> None:
        emitter = ObservabilityEmitter(_FakeEventLog())
        emitter.subscribe(make_routing_outcome_subscriber(self._store))

        emitter.emit(
            "routing.decision",
            {
                "session_id": "sess-1",
                "turn_number": 2,
                "task_type": "code_generation",
                "provider": "anthropic",
                "model": "claude-sonnet",
                "cost_usd": 0.004,
                "latency_ms": 900.0,
                "stage": "keywords",
                "confidence": 0.7,
            },
            turn_number=2,
        )

        recent = self._store.get_recent_outcomes()
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["task_type"], "code_generation")
        self.assertEqual(recent[0]["turn_number"], 2)
        self.assertEqual(recent[0]["stage"], "keywords")

    def test_non_routing_events_ignored(self) -> None:
        emitter = ObservabilityEmitter(_FakeEventLog())
        emitter.subscribe(make_routing_outcome_subscriber(self._store))
        emitter.emit("metric.api_call", {"model": "x"}, turn_number=1)
        self.assertEqual(self._store.get_recent_outcomes(), [])


if __name__ == "__main__":
    unittest.main()
