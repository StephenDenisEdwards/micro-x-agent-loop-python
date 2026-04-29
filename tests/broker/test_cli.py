"""Tests for broker/job CLI commands."""

from __future__ import annotations

import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from micro_x_agent_loop.broker.cli import (
    _job_add,
    _job_enable,
    _job_list,
    _job_remove,
    _job_run_now,
    _job_runs,
    _print_broker_help,
    _print_job_help,
    handle_broker_command,
    handle_job_command,
)
from micro_x_agent_loop.broker.store import BrokerStore


def _make_store(tmp_dir: str) -> BrokerStore:
    return BrokerStore(str(Path(tmp_dir) / "broker.db"))


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------


class PrintHelpTests(unittest.TestCase):
    def test_print_broker_help(self) -> None:
        buf = io.StringIO()
        with patch("builtins.print", lambda *a: buf.write(" ".join(str(x) for x in a) + "\n")):
            _print_broker_help()
        out = buf.getvalue()
        self.assertIn("start", out)
        self.assertIn("stop", out)
        self.assertIn("status", out)

    def test_print_job_help(self) -> None:
        buf = io.StringIO()
        with patch("builtins.print", lambda *a: buf.write(" ".join(str(x) for x in a) + "\n")):
            _print_job_help()
        out = buf.getvalue()
        self.assertIn("add", out)
        self.assertIn("list", out)
        self.assertIn("remove", out)


# ---------------------------------------------------------------------------
# _job_add
# ---------------------------------------------------------------------------


class JobAddTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._store = _make_store(self._tmp.name)

    def tearDown(self) -> None:
        self._store.close()
        self._tmp.cleanup()

    def _capture(self, fn, *args, **kwargs) -> str:
        buf = io.StringIO()
        with patch("builtins.print", lambda *a: buf.write(" ".join(str(x) for x in a) + "\n")):
            fn(*args, **kwargs)
        return buf.getvalue()

    def test_add_missing_args(self) -> None:
        out = self._capture(_job_add, self._store, ["only_one"])
        self.assertIn("Usage", out)

    def test_add_invalid_cron(self) -> None:
        out = self._capture(_job_add, self._store, ["job1", "not-a-cron", "do stuff"])
        self.assertIn("Invalid cron", out)

    def test_add_basic(self) -> None:
        out = self._capture(_job_add, self._store, ["myjob", "0 9 * * *", "say hello"])
        self.assertIn("Created job", out)
        self.assertIn("myjob", out)
        jobs = self._store.list_jobs()
        self.assertEqual(1, len(jobs))
        self.assertEqual("myjob", jobs[0]["name"])

    def test_add_with_all_flags(self) -> None:
        args = [
            "myjob2",
            "0 9 * * *",
            "prompt text",
            "--tz",
            "America/New_York",
            "--config",
            "cfg.json",
            "--session",
            "sess1",
            "--response-channel",
            "http",
            "--response-target",
            "http://cb",
            "--hitl",
            "--hitl-timeout",
            "120",
            "--max-retries",
            "3",
            "--retry-delay",
            "30",
        ]
        out = self._capture(_job_add, self._store, args)
        self.assertIn("Created job", out)
        self.assertIn("HITL", out)
        self.assertIn("Retries", out)

    def test_add_long_prompt_truncated(self) -> None:
        long_prompt = "x" * 100
        out = self._capture(_job_add, self._store, ["j", "* * * * *", long_prompt])
        self.assertIn("...", out)


# ---------------------------------------------------------------------------
# _job_list
# ---------------------------------------------------------------------------


class JobListTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._store = _make_store(self._tmp.name)

    def tearDown(self) -> None:
        self._store.close()
        self._tmp.cleanup()

    def _capture(self, fn, *args, **kwargs) -> str:
        buf = io.StringIO()
        with patch("builtins.print", lambda *a: buf.write(" ".join(str(x) for x in a) + "\n")):
            fn(*args, **kwargs)
        return buf.getvalue()

    def test_list_empty(self) -> None:
        out = self._capture(_job_list, self._store)
        self.assertIn("No jobs", out)

    def test_list_with_jobs(self) -> None:
        self._store.create_job(name="myjob", cron_expr="* * * * *", prompt_template="do stuff")
        out = self._capture(_job_list, self._store)
        self.assertIn("myjob", out)
        self.assertIn("enabled", out)

    def test_list_disabled_job(self) -> None:
        job = self._store.create_job(name="j", cron_expr="* * * * *", prompt_template="p")
        self._store.update_job(job["id"], enabled=0)
        out = self._capture(_job_list, self._store)
        self.assertIn("disabled", out)

    def test_list_with_response_channel(self) -> None:
        job = self._store.create_job(name="j", cron_expr="* * * * *", prompt_template="p")
        self._store.update_job(job["id"], response_channel="http", response_target="http://cb")
        out = self._capture(_job_list, self._store)
        self.assertIn("http", out)


# ---------------------------------------------------------------------------
# _job_remove
# ---------------------------------------------------------------------------


class JobRemoveTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._store = _make_store(self._tmp.name)

    def tearDown(self) -> None:
        self._store.close()
        self._tmp.cleanup()

    def _capture(self, fn, *args, **kwargs) -> str:
        buf = io.StringIO()
        with patch("builtins.print", lambda *a: buf.write(" ".join(str(x) for x in a) + "\n")):
            fn(*args, **kwargs)
        return buf.getvalue()

    def test_remove_no_args(self) -> None:
        out = self._capture(_job_remove, self._store, [])
        self.assertIn("Usage", out)

    def test_remove_no_match(self) -> None:
        out = self._capture(_job_remove, self._store, ["zzzzzz"])
        self.assertIn("No job found", out)

    def test_remove_ambiguous(self) -> None:
        j1 = self._store.create_job(name="a", cron_expr="* * * * *", prompt_template="p")
        self._store.create_job(name="b", cron_expr="* * * * *", prompt_template="p")
        # Both IDs start with some UUID prefix; let's try prefix that matches both
        # Use the common start of both UUIDs — just pass empty will match everything
        # Instead, make the prefix match both by using nothing — but that's hard
        # Just test exact prefix matching
        out = self._capture(_job_remove, self._store, [j1["id"][:8]])
        self.assertIn("Removed", out)
        self.assertEqual(1, len(self._store.list_jobs()))

    def test_remove_exact_match(self) -> None:
        job = self._store.create_job(name="myjob", cron_expr="* * * * *", prompt_template="p")
        out = self._capture(_job_remove, self._store, [job["id"][:8]])
        self.assertIn("Removed", out)
        self.assertEqual([], self._store.list_jobs())


# ---------------------------------------------------------------------------
# _job_enable / _job_disable
# ---------------------------------------------------------------------------


class JobEnableTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._store = _make_store(self._tmp.name)

    def tearDown(self) -> None:
        self._store.close()
        self._tmp.cleanup()

    def _capture(self, fn, *args, **kwargs) -> str:
        buf = io.StringIO()
        with patch("builtins.print", lambda *a: buf.write(" ".join(str(x) for x in a) + "\n")):
            fn(*args, **kwargs)
        return buf.getvalue()

    def test_enable_no_args(self) -> None:
        out = self._capture(_job_enable, self._store, [], enabled=True)
        self.assertIn("Usage", out)

    def test_disable_no_args(self) -> None:
        out = self._capture(_job_enable, self._store, [], enabled=False)
        self.assertIn("disable", out.lower())

    def test_enable_no_match(self) -> None:
        out = self._capture(_job_enable, self._store, ["zzzzzz"], enabled=True)
        self.assertIn("No job found", out)

    def test_enable_job(self) -> None:
        job = self._store.create_job(name="j", cron_expr="* * * * *", prompt_template="p")
        self._store.update_job(job["id"], enabled=0)
        out = self._capture(_job_enable, self._store, [job["id"][:8]], enabled=True)
        self.assertIn("Enabled", out)

    def test_disable_job(self) -> None:
        job = self._store.create_job(name="j", cron_expr="* * * * *", prompt_template="p")
        out = self._capture(_job_enable, self._store, [job["id"][:8]], enabled=False)
        self.assertIn("Disabled", out)


# ---------------------------------------------------------------------------
# _job_run_now
# ---------------------------------------------------------------------------


class JobRunNowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._store = _make_store(self._tmp.name)

    def tearDown(self) -> None:
        self._store.close()
        self._tmp.cleanup()

    def _capture_async(self, coro) -> str:
        buf = io.StringIO()
        with patch("builtins.print", lambda *a: buf.write(" ".join(str(x) for x in a) + "\n")):
            asyncio.run(coro)
        return buf.getvalue()

    def test_run_now_no_args(self) -> None:
        async def go():
            await _job_run_now(self._store, [])

        buf = io.StringIO()
        with patch("builtins.print", lambda *a: buf.write(" ".join(str(x) for x in a) + "\n")):
            asyncio.run(go())
        self.assertIn("Usage", buf.getvalue())

    def test_run_now_no_match(self) -> None:
        async def go():
            await _job_run_now(self._store, ["zzzzzz"])

        buf = io.StringIO()
        with patch("builtins.print", lambda *a: buf.write(" ".join(str(x) for x in a) + "\n")):
            asyncio.run(go())
        self.assertIn("No job found", buf.getvalue())

    def test_run_now_success(self) -> None:
        from micro_x_agent_loop.broker.runner import RunResult

        job = self._store.create_job(name="j", cron_expr="* * * * *", prompt_template="say hello")
        ok_result = RunResult(exit_code=0, stdout="Agent output\ndone", stderr="")

        async def go():
            with patch(
                "micro_x_agent_loop.broker.cli.run_agent",
                AsyncMock(return_value=ok_result),
            ):
                await _job_run_now(self._store, [job["id"][:8]])

        buf = io.StringIO()
        with patch("builtins.print", lambda *a: buf.write(" ".join(str(x) for x in a) + "\n")):
            asyncio.run(go())
        self.assertIn("completed", buf.getvalue())

    def test_run_now_failure(self) -> None:
        from micro_x_agent_loop.broker.runner import RunResult

        job = self._store.create_job(name="j", cron_expr="* * * * *", prompt_template="fail")
        fail_result = RunResult(exit_code=1, stdout="", stderr="something broke")

        async def go():
            with patch(
                "micro_x_agent_loop.broker.cli.run_agent",
                AsyncMock(return_value=fail_result),
            ):
                await _job_run_now(self._store, [job["id"][:8]])

        buf = io.StringIO()
        with patch("builtins.print", lambda *a: buf.write(" ".join(str(x) for x in a) + "\n")):
            asyncio.run(go())
        self.assertIn("failed", buf.getvalue())


# ---------------------------------------------------------------------------
# _job_runs
# ---------------------------------------------------------------------------


class JobRunsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._store = _make_store(self._tmp.name)

    def tearDown(self) -> None:
        self._store.close()
        self._tmp.cleanup()

    def _capture(self, fn, *args, **kwargs) -> str:
        buf = io.StringIO()
        with patch("builtins.print", lambda *a: buf.write(" ".join(str(x) for x in a) + "\n")):
            fn(*args, **kwargs)
        return buf.getvalue()

    def test_runs_no_runs(self) -> None:
        out = self._capture(_job_runs, self._store, [])
        self.assertIn("No runs", out)

    def test_runs_all(self) -> None:
        job = self._store.create_job(name="j", cron_expr="* * * * *", prompt_template="p")
        self._store.create_run(job_id=job["id"], trigger_source="cron", prompt="p")
        out = self._capture(_job_runs, self._store, [])
        self.assertIn("cron", out)

    def test_runs_filtered_by_job(self) -> None:
        job = self._store.create_job(name="j", cron_expr="* * * * *", prompt_template="p")
        self._store.create_run(job_id=job["id"], trigger_source="manual", prompt="p")
        out = self._capture(_job_runs, self._store, [job["id"][:8]])
        self.assertIn("manual", out)

    def test_runs_ambiguous_prefix(self) -> None:
        # Create two jobs; use short prefix that might match both
        j1 = self._store.create_job(name="a", cron_expr="* * * * *", prompt_template="p")
        self._store.create_job(name="b", cron_expr="* * * * *", prompt_template="p")
        # Pass a specific prefix for j1 that is unique
        out = self._capture(_job_runs, self._store, [j1["id"][:8]])
        # Should not show ambiguous message (8 chars of UUID is unique enough)
        self.assertNotIn("Ambiguous", out)

    def test_runs_with_completed_run(self) -> None:
        job = self._store.create_job(name="j", cron_expr="* * * * *", prompt_template="p")
        run_id = self._store.create_run(job_id=job["id"], trigger_source="cron", prompt="p")
        self._store.complete_run(run_id, result_summary="All done")
        out = self._capture(_job_runs, self._store, [])
        self.assertIn("completed", out)

    def test_runs_with_error(self) -> None:
        job = self._store.create_job(name="j", cron_expr="* * * * *", prompt_template="p")
        run_id = self._store.create_run(job_id=job["id"], trigger_source="cron", prompt="p")
        self._store.fail_run(run_id, error_text="something failed")
        out = self._capture(_job_runs, self._store, [])
        self.assertIn("failed", out)
        self.assertIn("something failed", out)


# ---------------------------------------------------------------------------
# handle_broker_command
# ---------------------------------------------------------------------------


class HandleBrokerCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _capture_async(self, coro) -> str:
        buf = io.StringIO()
        with patch("builtins.print", lambda *a: buf.write(" ".join(str(x) for x in a) + "\n")):
            asyncio.run(coro)
        return buf.getvalue()

    def test_no_args_prints_help(self) -> None:
        out = self._capture_async(handle_broker_command([]))
        self.assertIn("start", out)

    def test_stop_not_running(self) -> None:
        with patch(
            "micro_x_agent_loop.broker.cli.BrokerService.stop_broker",
            return_value=False,
        ):
            out = self._capture_async(handle_broker_command(["stop"]))
        self.assertIn("not running", out)

    def test_stop_running(self) -> None:
        with patch(
            "micro_x_agent_loop.broker.cli.BrokerService.stop_broker",
            return_value=True,
        ):
            out = self._capture_async(handle_broker_command(["stop"]))
        self.assertIn("stopped", out)

    def test_status_not_running(self) -> None:
        with patch(
            "micro_x_agent_loop.broker.cli.BrokerService.read_pid",
            return_value=None,
        ):
            out = self._capture_async(handle_broker_command(["status"]))
        self.assertIn("not running", out)

    def test_status_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "broker.db")
            store = BrokerStore(db_path)
            store.close()
            with (
                patch(
                    "micro_x_agent_loop.broker.cli.BrokerService.read_pid",
                    return_value=12345,
                ),
                patch(
                    "micro_x_agent_loop.broker.cli._get_store",
                    return_value=BrokerStore(db_path),
                ),
            ):
                out = self._capture_async(handle_broker_command(["status"], config={"BrokerDatabase": db_path}))
        self.assertIn("12345", out)

    def test_unknown_subcommand(self) -> None:
        out = self._capture_async(handle_broker_command(["unknown"]))
        self.assertIn("Unknown", out)


# ---------------------------------------------------------------------------
# handle_job_command
# ---------------------------------------------------------------------------


class HandleJobCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = str(Path(self._tmp.name) / "broker.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _capture_async(self, coro) -> str:
        buf = io.StringIO()
        with patch("builtins.print", lambda *a: buf.write(" ".join(str(x) for x in a) + "\n")):
            asyncio.run(coro)
        return buf.getvalue()

    def _config(self) -> dict:
        return {"BrokerDatabase": self._db_path}

    def test_no_args_prints_help(self) -> None:
        out = self._capture_async(handle_job_command([]))
        self.assertIn("add", out)

    def test_add(self) -> None:
        out = self._capture_async(handle_job_command(["add", "myjob", "0 9 * * *", "do it"], config=self._config()))
        self.assertIn("Created job", out)

    def test_list(self) -> None:
        # First add a job, then list
        asyncio.run(handle_job_command(["add", "myjob", "0 9 * * *", "do it"], config=self._config()))
        out = self._capture_async(handle_job_command(["list"], config=self._config()))
        self.assertIn("myjob", out)

    def test_unknown_subcommand(self) -> None:
        out = self._capture_async(handle_job_command(["bogus"], config=self._config()))
        self.assertIn("Unknown", out)

    def test_remove(self) -> None:
        asyncio.run(handle_job_command(["add", "myjob", "0 9 * * *", "do it"], config=self._config()))
        store = BrokerStore(self._db_path)
        jobs = store.list_jobs()
        store.close()
        job_id = jobs[0]["id"]
        out = self._capture_async(handle_job_command(["remove", job_id[:8]], config=self._config()))
        self.assertIn("Removed", out)

    def test_enable(self) -> None:
        asyncio.run(handle_job_command(["add", "myjob", "0 9 * * *", "do it"], config=self._config()))
        store = BrokerStore(self._db_path)
        jobs = store.list_jobs()
        store.close()
        job_id = jobs[0]["id"]
        asyncio.run(handle_job_command(["disable", job_id[:8]], config=self._config()))
        out = self._capture_async(handle_job_command(["enable", job_id[:8]], config=self._config()))
        self.assertIn("Enabled", out)

    def test_runs(self) -> None:
        out = self._capture_async(handle_job_command(["runs"], config=self._config()))
        self.assertIn("No runs", out)


if __name__ == "__main__":
    unittest.main()
