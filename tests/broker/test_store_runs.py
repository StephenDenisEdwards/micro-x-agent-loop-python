"""Tests for BrokerStore run/question/retry operations."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from micro_x_agent_loop.broker.store import BrokerStore


class BrokerStoreRunsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = str(Path(self._tmp.name) / "broker.db")
        self.store = BrokerStore(self._db_path)
        self.job = self.store.create_job(
            name="test-job",
            cron_expr="* * * * *",
            prompt_template="hello",
        )

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_set_run_response_info(self) -> None:
        run_id = self.store.create_run(
            job_id=self.job["id"], trigger_source="cron", prompt="p"
        )
        self.store.set_run_response_info(
            run_id, response_channel="http", response_target="http://cb"
        )
        run = self.store.get_run(run_id)
        self.assertEqual("http", run["response_channel"])
        self.assertEqual("http://cb", run["response_target"])

    def test_mark_response_sent(self) -> None:
        run_id = self.store.create_run(
            job_id=self.job["id"], trigger_source="cron", prompt="p"
        )
        self.store.mark_response_sent(run_id)
        run = self.store.get_run(run_id)
        self.assertEqual(1, run["response_sent"])

    def test_mark_response_failed(self) -> None:
        run_id = self.store.create_run(
            job_id=self.job["id"], trigger_source="cron", prompt="p"
        )
        self.store.mark_response_failed(run_id, error="delivery failed")
        run = self.store.get_run(run_id)
        self.assertEqual("delivery failed", run["response_error"])

    def test_list_runs_all(self) -> None:
        self.store.create_run(job_id=self.job["id"], trigger_source="cron", prompt="a")
        self.store.create_run(job_id=self.job["id"], trigger_source="cron", prompt="b")
        runs = self.store.list_runs()
        self.assertGreaterEqual(len(runs), 2)

    def test_list_runs_filtered_by_job(self) -> None:
        job2 = self.store.create_job(name="j2", cron_expr="* * * * *", prompt_template="p2")
        self.store.create_run(job_id=self.job["id"], trigger_source="cron", prompt="a")
        self.store.create_run(job_id=job2["id"], trigger_source="cron", prompt="b")
        runs = self.store.list_runs(job_id=self.job["id"])
        self.assertEqual(1, len(runs))
        self.assertEqual(self.job["id"], runs[0]["job_id"])

    def test_create_run_if_no_overlap_creates_run(self) -> None:
        run_id = self.store.create_run_if_no_overlap(
            job_id=self.job["id"], trigger_source="cron", prompt="p"
        )
        self.assertIsNotNone(run_id)

    def test_create_run_if_no_overlap_skips_when_running(self) -> None:
        # Create a running run first
        self.store.create_run(
            job_id=self.job["id"], trigger_source="cron", prompt="p"
        )
        # Now try to create with no overlap — should return None
        run_id = self.store.create_run_if_no_overlap(
            job_id=self.job["id"], trigger_source="cron", prompt="p2"
        )
        self.assertIsNone(run_id)


class BrokerStoreQuestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = str(Path(self._tmp.name) / "broker.db")
        self.store = BrokerStore(self._db_path)
        self.job = self.store.create_job(
            name="q-job", cron_expr="* * * * *", prompt_template="p"
        )
        self.run_id = self.store.create_run(
            job_id=self.job["id"], trigger_source="cron", prompt="q"
        )

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_create_and_get_question(self) -> None:
        qid = self.store.create_question(
            run_id=self.run_id,
            question_text="Proceed?",
            timeout_seconds=300,
        )
        q = self.store.get_question(qid)
        self.assertIsNotNone(q)
        self.assertEqual("Proceed?", q["question_text"])
        self.assertEqual("pending", q["status"])

    def test_answer_question(self) -> None:
        qid = self.store.create_question(
            run_id=self.run_id,
            question_text="Yes or no?",
            timeout_seconds=300,
        )
        answered = self.store.answer_question(qid, answer="yes")
        self.assertTrue(answered)
        q = self.store.get_question(qid)
        self.assertEqual("answered", q["status"])
        self.assertEqual("yes", q["answer"])

    def test_answer_already_answered_returns_false(self) -> None:
        qid = self.store.create_question(
            run_id=self.run_id,
            question_text="Q?",
            timeout_seconds=300,
        )
        self.store.answer_question(qid, answer="a")
        result = self.store.answer_question(qid, answer="b")
        self.assertFalse(result)

    def test_get_pending_question(self) -> None:
        qid = self.store.create_question(
            run_id=self.run_id,
            question_text="Still pending",
            timeout_seconds=300,
        )
        q = self.store.get_pending_question(self.run_id)
        self.assertIsNotNone(q)
        self.assertEqual(qid, q["id"])

    def test_get_pending_question_none_when_answered(self) -> None:
        qid = self.store.create_question(
            run_id=self.run_id,
            question_text="Q?",
            timeout_seconds=300,
        )
        self.store.answer_question(qid, answer="done")
        q = self.store.get_pending_question(self.run_id)
        self.assertIsNone(q)

    def test_get_question_timed_out(self) -> None:
        qid = self.store.create_question(
            run_id=self.run_id,
            question_text="Expired?",
            timeout_seconds=0,  # immediate timeout
        )
        # Wait a tiny bit so timeout_at <= now
        time.sleep(0.01)
        q = self.store.get_question(qid)
        self.assertEqual("timed_out", q["status"])

    def test_get_pending_question_returns_none_after_timeout(self) -> None:
        self.store.create_question(
            run_id=self.run_id,
            question_text="T?",
            timeout_seconds=0,
        )
        time.sleep(0.01)
        q = self.store.get_pending_question(self.run_id)
        self.assertIsNone(q)


class BrokerStoreRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = str(Path(self._tmp.name) / "broker.db")
        self.store = BrokerStore(self._db_path)
        self.job = self.store.create_job(
            name="retry-job", cron_expr="* * * * *", prompt_template="p"
        )

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_create_retry_run(self) -> None:
        from datetime import UTC, datetime, timedelta
        scheduled_at = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
        retry_id = self.store.create_retry_run(
            job_id=self.job["id"],
            trigger_source="retry",
            prompt="retry prompt",
            attempt_number=2,
            scheduled_at=scheduled_at,
        )
        self.assertIsNotNone(retry_id)
        run = self.store.get_run(retry_id)
        self.assertIsNotNone(run)
        self.assertEqual("queued", run["status"])
        self.assertEqual(2, run["attempt_number"])

    def test_list_due_retries(self) -> None:
        from datetime import UTC, datetime, timedelta
        # Past scheduled time
        past_time = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
        retry_id = self.store.create_retry_run(
            job_id=self.job["id"],
            trigger_source="retry",
            prompt="p",
            attempt_number=2,
            scheduled_at=past_time,
        )
        retries = self.store.list_due_retries()
        ids = [r["id"] for r in retries]
        self.assertIn(retry_id, ids)

    def test_start_run(self) -> None:
        from datetime import UTC, datetime, timedelta
        scheduled_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        retry_id = self.store.create_retry_run(
            job_id=self.job["id"],
            trigger_source="retry",
            prompt="p",
            attempt_number=2,
            scheduled_at=scheduled_at,
        )
        self.store.start_run(retry_id)
        run = self.store.get_run(retry_id)
        self.assertEqual("running", run["status"])


if __name__ == "__main__":
    unittest.main()
