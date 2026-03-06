"""Tests for the broker job store."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from micro_x_agent_loop.broker.store import BrokerStore


class BrokerStoreJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = str(Path(self._tmp.name) / "broker.db")
        self.store = BrokerStore(self._db_path)

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_create_and_get_job(self) -> None:
        job = self.store.create_job(
            name="test-job",
            cron_expr="0 9 * * *",
            prompt_template="Say hello",
        )
        self.assertEqual(job["name"], "test-job")
        self.assertEqual(job["cron_expr"], "0 9 * * *")
        self.assertEqual(job["prompt_template"], "Say hello")
        self.assertEqual(job["enabled"], 1)
        self.assertEqual(job["overlap_policy"], "skip_if_running")

        fetched = self.store.get_job(job["id"])
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["name"], "test-job")

    def test_list_jobs(self) -> None:
        self.store.create_job(name="a", cron_expr="* * * * *", prompt_template="p1")
        self.store.create_job(name="b", cron_expr="* * * * *", prompt_template="p2")
        jobs = self.store.list_jobs()
        self.assertEqual(len(jobs), 2)

    def test_list_jobs_enabled_only(self) -> None:
        j1 = self.store.create_job(name="a", cron_expr="* * * * *", prompt_template="p1")
        self.store.create_job(name="b", cron_expr="* * * * *", prompt_template="p2")
        self.store.update_job(j1["id"], enabled=0)
        jobs = self.store.list_jobs(enabled_only=True)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["name"], "b")

    def test_update_job(self) -> None:
        job = self.store.create_job(name="x", cron_expr="* * * * *", prompt_template="p")
        self.store.update_job(job["id"], name="y", cron_expr="0 0 * * *")
        updated = self.store.get_job(job["id"])
        self.assertEqual(updated["name"], "y")
        self.assertEqual(updated["cron_expr"], "0 0 * * *")

    def test_delete_job(self) -> None:
        job = self.store.create_job(name="x", cron_expr="* * * * *", prompt_template="p")
        result = self.store.delete_job(job["id"])
        self.assertTrue(result)
        self.assertIsNone(self.store.get_job(job["id"]))

    def test_delete_nonexistent_job(self) -> None:
        result = self.store.delete_job("nonexistent")
        self.assertFalse(result)

    def test_get_nonexistent_job(self) -> None:
        self.assertIsNone(self.store.get_job("nonexistent"))


class BrokerStoreRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = str(Path(self._tmp.name) / "broker.db")
        self.store = BrokerStore(self._db_path)
        self.job = self.store.create_job(
            name="test-job",
            cron_expr="* * * * *",
            prompt_template="test prompt",
        )

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_create_and_complete_run(self) -> None:
        run_id = self.store.create_run(
            job_id=self.job["id"],
            trigger_source="cron",
            prompt="test prompt",
        )
        self.assertTrue(self.store.has_running_run(self.job["id"]))
        self.store.complete_run(run_id, result_summary="done")
        self.assertFalse(self.store.has_running_run(self.job["id"]))

    def test_fail_run(self) -> None:
        run_id = self.store.create_run(
            job_id=self.job["id"],
            trigger_source="cron",
            prompt="test",
        )
        self.store.fail_run(run_id, error_text="boom")
        runs = self.store.list_runs(self.job["id"])
        self.assertEqual(runs[0]["status"], "failed")
        self.assertEqual(runs[0]["error_text"], "boom")

    def test_skip_run(self) -> None:
        run_id = self.store.create_run(
            job_id=self.job["id"],
            trigger_source="cron",
            prompt="test",
        )
        self.store.skip_run(run_id)
        runs = self.store.list_runs(self.job["id"])
        self.assertEqual(runs[0]["status"], "skipped")

    def test_has_running_run(self) -> None:
        self.assertFalse(self.store.has_running_run(self.job["id"]))
        run_id = self.store.create_run(
            job_id=self.job["id"],
            trigger_source="cron",
            prompt="test",
        )
        self.assertTrue(self.store.has_running_run(self.job["id"]))
        self.store.complete_run(run_id)
        self.assertFalse(self.store.has_running_run(self.job["id"]))

    def test_list_runs_with_limit(self) -> None:
        for i in range(5):
            rid = self.store.create_run(
                job_id=self.job["id"],
                trigger_source="cron",
                prompt=f"test {i}",
            )
            self.store.complete_run(rid)
        runs = self.store.list_runs(self.job["id"], limit=3)
        self.assertEqual(len(runs), 3)

    def test_ad_hoc_run_no_job_id(self) -> None:
        self.store.create_run(
            job_id=None,
            trigger_source="manual",
            prompt="ad hoc",
        )
        runs = self.store.list_runs()
        self.assertEqual(len(runs), 1)
        self.assertIsNone(runs[0]["job_id"])


class BrokerStoreReopenTests(unittest.TestCase):
    """Test that data persists across store instances."""

    def test_data_persists(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        db_path = str(Path(tmp.name) / "broker.db")

        store1 = BrokerStore(db_path)
        store1.create_job(name="persist-test", cron_expr="* * * * *", prompt_template="p")
        store1.close()

        store2 = BrokerStore(db_path)
        jobs = store2.list_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["name"], "persist-test")
        store2.close()
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
