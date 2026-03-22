"""Extended scheduler tests covering Scheduler class."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from micro_x_agent_loop.broker.dispatcher import RunDispatcher
from micro_x_agent_loop.broker.response_router import ResponseRouter
from micro_x_agent_loop.broker.runner import RunResult
from micro_x_agent_loop.broker.scheduler import Scheduler
from micro_x_agent_loop.broker.store import BrokerStore


def _make_store(tmp_dir: str) -> BrokerStore:
    return BrokerStore(str(Path(tmp_dir) / "broker.db"))


def _make_router() -> ResponseRouter:
    adapter = MagicMock()
    adapter.send_response = AsyncMock(return_value=True)
    return ResponseRouter({"log": adapter})


class SchedulerStopTests(unittest.TestCase):
    def test_stop_sets_event(self) -> None:
        store = MagicMock()
        dispatcher = MagicMock()
        sched = Scheduler(store, dispatcher, poll_interval=5)
        self.assertFalse(sched._stop_event.is_set())
        sched.stop()
        self.assertTrue(sched._stop_event.is_set())


class SchedulerInitialiseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._store = _make_store(self._tmp.name)

    def tearDown(self) -> None:
        self._store.close()
        self._tmp.cleanup()

    def test_initialise_sets_next_run(self) -> None:
        job = self._store.create_job(
            name="j", cron_expr="0 9 * * *", prompt_template="p"
        )
        dispatcher = MagicMock()
        sched = Scheduler(self._store, dispatcher, poll_interval=5)
        sched._initialise_schedules()
        updated = self._store.get_job(job["id"])
        self.assertIsNotNone(updated["next_run_at"])

    def test_initialise_skip_policy_advances_past_run(self) -> None:
        job = self._store.create_job(
            name="j", cron_expr="0 9 * * *", prompt_template="p"
        )
        # Set next_run_at to the past
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        self._store.update_job(job["id"], next_run_at=past)

        dispatcher = MagicMock()
        sched = Scheduler(self._store, dispatcher, poll_interval=5, recovery_policy="skip")
        sched._initialise_schedules()
        updated = self._store.get_job(job["id"])
        # Should have advanced to a future time
        self.assertGreater(updated["next_run_at"], datetime.now(UTC).isoformat())

    def test_initialise_run_once_policy_leaves_past(self) -> None:
        job = self._store.create_job(
            name="j", cron_expr="0 9 * * *", prompt_template="p"
        )
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        self._store.update_job(job["id"], next_run_at=past)

        dispatcher = MagicMock()
        sched = Scheduler(self._store, dispatcher, poll_interval=5, recovery_policy="run_once")
        sched._initialise_schedules()
        updated = self._store.get_job(job["id"])
        # Should NOT have advanced — left in the past for the poll to pick up
        self.assertEqual(past, updated["next_run_at"])


class SchedulerPollAndDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._store = _make_store(self._tmp.name)

    def tearDown(self) -> None:
        self._store.close()
        self._tmp.cleanup()

    def test_poll_dispatches_due_job(self) -> None:
        async def go() -> None:
            ok_result = RunResult(exit_code=0, stdout="done", stderr="")
            router = _make_router()
            dispatcher = RunDispatcher(self._store, router)

            job = self._store.create_job(
                name="due-job", cron_expr="* * * * *", prompt_template="hello"
            )
            # Set next_run_at to the past so it's due
            past = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
            self._store.update_job(job["id"], next_run_at=past)

            sched = Scheduler(self._store, dispatcher, poll_interval=5)
            with patch(
                "micro_x_agent_loop.broker.dispatcher.run_agent",
                AsyncMock(return_value=ok_result),
            ):
                await sched._poll_and_dispatch()
                await dispatcher.wait_for_all()

            runs = self._store.list_runs(job_id=job["id"])
            self.assertGreaterEqual(len(runs), 1)

        asyncio.run(go())

    def test_poll_skips_not_due_job(self) -> None:
        async def go() -> None:
            dispatcher = MagicMock()
            dispatcher.at_capacity = False

            job = self._store.create_job(
                name="future-job", cron_expr="0 9 * * *", prompt_template="p"
            )
            future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
            self._store.update_job(job["id"], next_run_at=future)

            sched = Scheduler(self._store, dispatcher, poll_interval=5)
            await sched._poll_and_dispatch()

            dispatcher.dispatch.assert_not_called()

        asyncio.run(go())

    def test_poll_skips_when_at_capacity(self) -> None:
        async def go() -> None:
            dispatcher = MagicMock()
            dispatcher.at_capacity = True

            job = self._store.create_job(
                name="j", cron_expr="* * * * *", prompt_template="p"
            )
            past = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
            self._store.update_job(job["id"], next_run_at=past)

            sched = Scheduler(self._store, dispatcher, poll_interval=5)
            await sched._poll_and_dispatch()

            dispatcher.dispatch.assert_not_called()

        asyncio.run(go())

    def test_poll_overlap_policy_skip_if_running(self) -> None:
        async def go() -> None:
            dispatcher = MagicMock()
            dispatcher.at_capacity = False

            job = self._store.create_job(
                name="j", cron_expr="* * * * *", prompt_template="p",
                overlap_policy="skip_if_running",
            )
            past = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
            self._store.update_job(job["id"], next_run_at=past)

            # Create a running run to trigger overlap skip
            self._store.create_run(job_id=job["id"], trigger_source="cron", prompt="p")

            sched = Scheduler(self._store, dispatcher, poll_interval=5)
            await sched._poll_and_dispatch()

            dispatcher.dispatch.assert_not_called()

        asyncio.run(go())

    def test_poll_dispatches_due_retries(self) -> None:
        async def go() -> None:
            ok_result = RunResult(exit_code=0, stdout="done", stderr="")
            router = _make_router()
            dispatcher = RunDispatcher(self._store, router)

            job = self._store.create_job(
                name="j", cron_expr="* * * * *", prompt_template="p"
            )
            past = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
            retry_id = self._store.create_retry_run(
                job_id=job["id"],
                trigger_source="retry",
                prompt="p",
                attempt_number=2,
                scheduled_at=past,
            )

            sched = Scheduler(self._store, dispatcher, poll_interval=5)
            with patch(
                "micro_x_agent_loop.broker.dispatcher.run_agent",
                AsyncMock(return_value=ok_result),
            ):
                await sched._poll_and_dispatch()
                await dispatcher.wait_for_all()

            retry = self._store.get_run(retry_id)
            # Should have been started (status changed from queued)
            self.assertNotEqual("queued", retry["status"])

        asyncio.run(go())


class SchedulerStartStopTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._store = _make_store(self._tmp.name)

    def tearDown(self) -> None:
        self._store.close()
        self._tmp.cleanup()

    def test_start_and_stop(self) -> None:
        async def go() -> None:
            dispatcher = MagicMock()
            dispatcher.at_capacity = False
            dispatcher.dispatch = MagicMock()

            sched = Scheduler(self._store, dispatcher, poll_interval=0)

            async def stop_soon() -> None:
                await asyncio.sleep(0.05)
                sched.stop()

            await asyncio.gather(sched.start(), stop_soon())

        asyncio.run(go())

    def test_start_stops_on_max_errors(self) -> None:
        async def go() -> None:
            dispatcher = MagicMock()
            dispatcher.at_capacity = False

            sched = Scheduler(self._store, dispatcher, poll_interval=0)

            call_count = 0

            async def failing_poll():
                nonlocal call_count
                call_count += 1
                raise RuntimeError("poll error")

            sched._poll_and_dispatch = failing_poll
            # Loop should stop after 10 consecutive errors
            await asyncio.wait_for(sched.start(), timeout=5.0)
            self.assertGreaterEqual(call_count, 10)

        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
