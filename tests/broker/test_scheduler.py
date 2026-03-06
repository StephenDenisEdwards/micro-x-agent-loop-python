"""Tests for the broker scheduler."""

from __future__ import annotations

import tempfile
import unittest
from datetime import UTC
from pathlib import Path

from croniter import croniter

from micro_x_agent_loop.broker.scheduler import compute_next_run
from micro_x_agent_loop.broker.store import BrokerStore


class ComputeNextRunTests(unittest.TestCase):
    def test_returns_iso_string(self) -> None:
        result = compute_next_run("0 9 * * *", "UTC")
        # Should be a valid ISO 8601 string with timezone info
        self.assertIn("T", result)
        self.assertTrue(result.endswith("+00:00"))

    def test_next_run_is_in_future(self) -> None:
        from datetime import datetime
        result = compute_next_run("* * * * *", "UTC")
        next_dt = datetime.fromisoformat(result)
        now = datetime.now(UTC)
        self.assertGreater(next_dt, now)

    def test_respects_timezone(self) -> None:
        # Just verify it doesn't crash with a non-UTC timezone
        result = compute_next_run("0 9 * * *", "America/New_York")
        self.assertIn("T", result)


class SchedulerOverlapPolicyTests(unittest.TestCase):
    """Test that overlap detection works at the store level."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = str(Path(self._tmp.name) / "broker.db")
        self.store = BrokerStore(self._db_path)
        self.job = self.store.create_job(
            name="overlap-test",
            cron_expr="* * * * *",
            prompt_template="test",
            overlap_policy="skip_if_running",
        )

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_skip_if_running_blocks_concurrent(self) -> None:
        run_id = self.store.create_run(
            job_id=self.job["id"],
            trigger_source="cron",
            prompt="test",
        )
        # While run is active, has_running_run should be True
        self.assertTrue(self.store.has_running_run(self.job["id"]))

        # After completion, should allow new runs
        self.store.complete_run(run_id)
        self.assertFalse(self.store.has_running_run(self.job["id"]))


class CronExpressionValidationTests(unittest.TestCase):
    def test_valid_expressions(self) -> None:
        valid = [
            "* * * * *",        # every minute
            "0 9 * * *",        # daily at 9am
            "0 0 * * 1",        # weekly on Monday
            "0 0 1 * *",        # monthly on 1st
            "*/5 * * * *",      # every 5 minutes
            "0 9,17 * * 1-5",   # 9am and 5pm weekdays
        ]
        for expr in valid:
            with self.subTest(expr=expr):
                self.assertTrue(croniter.is_valid(expr), f"{expr} should be valid")

    def test_invalid_expressions(self) -> None:
        invalid = [
            "not a cron",
            "60 * * * *",       # invalid minute
        ]
        for expr in invalid:
            with self.subTest(expr=expr):
                self.assertFalse(croniter.is_valid(expr), f"{expr} should be invalid")


if __name__ == "__main__":
    unittest.main()
