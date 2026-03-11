"""Tests for broker runner module."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from micro_x_agent_loop.broker.runner import RunResult, _truncate_output, run_agent


class RunResultTests(unittest.TestCase):
    def test_ok_true_when_exit_code_zero(self) -> None:
        r = RunResult(exit_code=0, stdout="done", stderr="")
        self.assertTrue(r.ok)

    def test_ok_false_when_nonzero_exit(self) -> None:
        r = RunResult(exit_code=1, stdout="", stderr="err")
        self.assertFalse(r.ok)

    def test_summary_last_five_lines(self) -> None:
        lines = [f"line{i}" for i in range(10)]
        r = RunResult(exit_code=0, stdout="\n".join(lines), stderr="")
        summary = r.summary
        self.assertIn("line9", summary)
        self.assertIn("line5", summary)
        self.assertNotIn("line4", summary)

    def test_summary_empty_stdout(self) -> None:
        r = RunResult(exit_code=0, stdout="", stderr="")
        self.assertEqual("(no output)", r.summary)

    def test_summary_whitespace_only(self) -> None:
        r = RunResult(exit_code=0, stdout="   \n   ", stderr="")
        self.assertEqual("(no output)", r.summary)

    def test_summary_fewer_than_five_lines(self) -> None:
        r = RunResult(exit_code=0, stdout="a\nb\nc", stderr="")
        summary = r.summary
        self.assertIn("a", summary)
        self.assertIn("c", summary)


class TruncateOutputTests(unittest.TestCase):
    def test_short_output_unchanged(self) -> None:
        data = b"hello world"
        result = _truncate_output(data, "stdout")
        self.assertEqual("hello world", result)

    def test_large_output_truncated(self) -> None:
        limit = 10 * 1024 * 1024  # 10 MB
        data = b"x" * (limit + 1000)
        result = _truncate_output(data, "stdout")
        self.assertEqual(limit, len(result))

    def test_handles_invalid_utf8(self) -> None:
        data = b"\xff\xfe" + b"hello"
        result = _truncate_output(data, "stdout")
        self.assertIsInstance(result, str)


class RunAgentTests(unittest.TestCase):
    def _make_mock_process(self, stdout: bytes = b"output", stderr: bytes = b"", returncode: int = 0) -> MagicMock:
        process = MagicMock()
        process.returncode = returncode
        process.communicate = AsyncMock(return_value=(stdout, stderr))
        process.kill = MagicMock()
        process.wait = AsyncMock()
        return process

    def test_success(self) -> None:
        process = self._make_mock_process(stdout=b"done", returncode=0)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            result = asyncio.run(run_agent(prompt="hello"))
        self.assertTrue(result.ok)
        self.assertEqual("done", result.stdout)

    def test_failure_exit_code(self) -> None:
        process = self._make_mock_process(stdout=b"", stderr=b"error msg", returncode=1)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            result = asyncio.run(run_agent(prompt="fail"))
        self.assertFalse(result.ok)
        self.assertEqual("error msg", result.stderr)

    def test_with_config_and_session(self) -> None:
        process = self._make_mock_process()
        mock_create = AsyncMock(return_value=process)
        with patch("asyncio.create_subprocess_exec", mock_create):
            asyncio.run(run_agent(prompt="hi", config="cfg.json", session_id="s1"))
        call_args = mock_create.call_args[0]
        self.assertIn("--config", call_args)
        self.assertIn("cfg.json", call_args)
        self.assertIn("--session", call_args)
        self.assertIn("s1", call_args)

    def test_extra_env_merged(self) -> None:
        process = self._make_mock_process()
        mock_create = AsyncMock(return_value=process)
        with patch("asyncio.create_subprocess_exec", mock_create):
            asyncio.run(run_agent(prompt="hi", extra_env={"MY_VAR": "42"}))
        kwargs = mock_create.call_args[1]
        self.assertIn("env", kwargs)
        self.assertEqual("42", kwargs["env"]["MY_VAR"])

    def test_no_extra_env(self) -> None:
        process = self._make_mock_process()
        mock_create = AsyncMock(return_value=process)
        with patch("asyncio.create_subprocess_exec", mock_create):
            asyncio.run(run_agent(prompt="hi"))
        kwargs = mock_create.call_args[1]
        self.assertIsNone(kwargs["env"])

    def test_timeout(self) -> None:
        async def slow_communicate():
            await asyncio.sleep(100)
            return (b"", b"")

        process = MagicMock()
        process.returncode = -1
        process.communicate = slow_communicate
        process.kill = MagicMock()
        process.wait = AsyncMock()

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            result = asyncio.run(run_agent(prompt="slow", timeout_seconds=0))
        self.assertFalse(result.ok)
        self.assertIn("timed out", result.stderr)

    def test_spawn_exception(self) -> None:
        with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=OSError("spawn failed"))):
            result = asyncio.run(run_agent(prompt="fail"))
        self.assertFalse(result.ok)
        self.assertIn("spawn failed", result.stderr)


if __name__ == "__main__":
    unittest.main()
