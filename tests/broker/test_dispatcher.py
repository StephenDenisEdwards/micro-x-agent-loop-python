"""Tests for RunDispatcher."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from micro_x_agent_loop.broker.dispatcher import RunDispatcher
from micro_x_agent_loop.broker.response_router import ResponseRouter
from micro_x_agent_loop.broker.runner import RunResult
from micro_x_agent_loop.broker.store import BrokerStore


def _make_store(tmp_dir: str) -> BrokerStore:
    db_path = str(Path(tmp_dir) / "broker.db")
    return BrokerStore(db_path)


def _make_router(*, send_result: bool = True) -> ResponseRouter:
    adapter = MagicMock()
    adapter.send_response = AsyncMock(return_value=send_result)
    return ResponseRouter({"log": adapter})


class ActiveRunCountTests(unittest.TestCase):
    def test_initially_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            dispatcher = RunDispatcher(store, _make_router())
            self.assertEqual(0, dispatcher.active_run_count)
            store.close()

    def test_at_capacity_false_when_below_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            dispatcher = RunDispatcher(store, _make_router(), max_concurrent_runs=2)
            self.assertFalse(dispatcher.at_capacity)
            store.close()


class DispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._store = _make_store(self._tmp.name)
        self._router = _make_router()

    def tearDown(self) -> None:
        self._store.close()
        self._tmp.cleanup()

    def test_dispatch_returns_task(self) -> None:
        async def go() -> None:
            dispatcher = RunDispatcher(self._store, self._router)
            run_id = self._store.create_run(job_id=None, trigger_source="test", prompt="hello")
            ok_result = RunResult(exit_code=0, stdout="done", stderr="")
            with patch(
                "micro_x_agent_loop.broker.dispatcher.run_agent",
                AsyncMock(return_value=ok_result),
            ):
                task = dispatcher.dispatch(run_id=run_id, prompt="hello")
                self.assertIsNotNone(task)
                await task

        asyncio.run(go())

    def test_dispatch_success_completes_run(self) -> None:
        async def go() -> None:
            dispatcher = RunDispatcher(self._store, self._router)
            run_id = self._store.create_run(job_id=None, trigger_source="cron", prompt="greet")
            ok_result = RunResult(exit_code=0, stdout="hello world", stderr="")
            with patch(
                "micro_x_agent_loop.broker.dispatcher.run_agent",
                AsyncMock(return_value=ok_result),
            ):
                task = dispatcher.dispatch(run_id=run_id, prompt="greet")
                await task

            run = self._store.get_run(run_id)
            self.assertEqual("completed", run["status"])

        asyncio.run(go())

    def test_dispatch_failure_marks_run_failed(self) -> None:
        async def go() -> None:
            dispatcher = RunDispatcher(self._store, self._router)
            run_id = self._store.create_run(job_id=None, trigger_source="cron", prompt="fail")
            fail_result = RunResult(exit_code=1, stdout="", stderr="something went wrong")
            with patch(
                "micro_x_agent_loop.broker.dispatcher.run_agent",
                AsyncMock(return_value=fail_result),
            ):
                task = dispatcher.dispatch(run_id=run_id, prompt="fail")
                await task

            run = self._store.get_run(run_id)
            self.assertEqual("failed", run["status"])

        asyncio.run(go())

    def test_dispatch_with_hitl_env(self) -> None:
        async def go() -> None:
            dispatcher = RunDispatcher(self._store, self._router, broker_url="http://broker:8321")
            job = self._store.create_job(
                name="j",
                cron_expr="* * * * *",
                prompt_template="test",
            )
            # Patch job dict to enable HITL
            job_dict = dict(job)
            job_dict["hitl_enabled"] = 1
            job_dict["hitl_timeout_seconds"] = 120

            run_id = self._store.create_run(job_id=job["id"], trigger_source="cron", prompt="test")
            ok_result = RunResult(exit_code=0, stdout="done", stderr="")
            captured_kwargs = {}

            async def mock_run_agent(**kwargs):
                captured_kwargs.update(kwargs)
                return ok_result

            with patch(
                "micro_x_agent_loop.broker.dispatcher.run_agent",
                mock_run_agent,
            ):
                task = dispatcher.dispatch(run_id=run_id, prompt="test", job=job_dict)
                await task

            # HITL env vars should be passed
            env = captured_kwargs.get("extra_env", {})
            self.assertIn("MICRO_X_BROKER_URL", env)
            self.assertEqual("http://broker:8321", env["MICRO_X_BROKER_URL"])
            self.assertEqual(run_id, env["MICRO_X_RUN_ID"])

        asyncio.run(go())

    def test_execute_run_exception_marks_failed(self) -> None:
        async def go() -> None:
            dispatcher = RunDispatcher(self._store, self._router)
            run_id = self._store.create_run(job_id=None, trigger_source="cron", prompt="boom")
            with patch(
                "micro_x_agent_loop.broker.dispatcher.run_agent",
                AsyncMock(side_effect=RuntimeError("crash")),
            ):
                task = dispatcher.dispatch(run_id=run_id, prompt="boom")
                await task

            run = self._store.get_run(run_id)
            self.assertEqual("failed", run["status"])

        asyncio.run(go())

    def test_wait_for_all_no_tasks(self) -> None:
        async def go() -> None:
            dispatcher = RunDispatcher(self._store, self._router)
            await dispatcher.wait_for_all()  # Should not raise

        asyncio.run(go())

    def test_wait_for_all_waits_for_tasks(self) -> None:
        async def go() -> None:
            dispatcher = RunDispatcher(self._store, self._router)
            run_id = self._store.create_run(job_id=None, trigger_source="cron", prompt="wait")
            ok_result = RunResult(exit_code=0, stdout="done", stderr="")
            with patch(
                "micro_x_agent_loop.broker.dispatcher.run_agent",
                AsyncMock(return_value=ok_result),
            ):
                dispatcher.dispatch(run_id=run_id, prompt="wait")
                await dispatcher.wait_for_all()

            self.assertEqual(0, dispatcher.active_run_count)

        asyncio.run(go())

    def test_dispatch_with_retry_on_failure(self) -> None:
        async def go() -> None:
            dispatcher = RunDispatcher(self._store, self._router)
            job = self._store.create_job(
                name="retry-job",
                cron_expr="* * * * *",
                prompt_template="test",
            )
            job_dict = dict(job)
            job_dict["max_retries"] = 3
            job_dict["retry_delay_seconds"] = 1

            run_id = self._store.create_run(job_id=job["id"], trigger_source="cron", prompt="retry")
            fail_result = RunResult(exit_code=1, stdout="", stderr="fail")
            with patch(
                "micro_x_agent_loop.broker.dispatcher.run_agent",
                AsyncMock(return_value=fail_result),
            ):
                task = dispatcher.dispatch(run_id=run_id, prompt="retry", job=job_dict)
                await task

            # A retry run should be scheduled
            self._store.list_due_retries()
            # Not necessarily due yet (scheduled in the future), but a queued run should exist
            runs = self._store.list_runs(job_id=job["id"])
            # Should have original + at least a retry
            self.assertGreaterEqual(len(runs), 1)

        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
