"""Characterization tests for F4 native bash tool. Security-sensitive —
pins the containment behaviour verbatim: allowlist modes, path-guard
absolute/traversal rejection + disable, and execution semantics
(exit code, no-output, timeout, output truncation). No TS suite existed.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest import mock

from micro_x_agent_loop.native_tools.filesystem import bash_tool
from micro_x_agent_loop.native_tools.filesystem.bash_tool import BashTool
from micro_x_agent_loop.native_tools.filesystem.paths import PathPolicy


def _run(coro):
    return asyncio.run(coro)


def _bash_available() -> bool:
    bash_tool._shell_cache = None
    try:
        bash_tool._resolve_bash_shell()
        return True
    except RuntimeError:
        return False


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        self.policy = PathPolicy(self.root)
        self.addCleanup(self._tmp.cleanup)

    def _tool(self, env: dict[str, str] | None = None) -> BashTool:
        with mock.patch.dict(os.environ, env or {}, clear=False):
            return BashTool(self.policy)


class AllowlistTests(_Base):
    def test_deny_all_kill_switch(self) -> None:
        t = self._tool({"FILESYSTEM_BASH_ALLOWED_COMMANDS": ""})
        r = _run(t.execute({"command": "echo hi"}))
        self.assertTrue(r.is_error)
        self.assertIn("bash is disabled", r.text)

    def test_list_miss(self) -> None:
        t = self._tool({"FILESYSTEM_BASH_ALLOWED_COMMANDS": "git, npm"})
        r = _run(t.execute({"command": "rm -rf /"}))
        self.assertTrue(r.is_error)
        self.assertIn('command "rm" is not in', r.text)
        self.assertIn("allowed: git, npm", r.text)

    def test_list_hit(self) -> None:
        if not _bash_available():
            self.skipTest("no bash shell")
        t = self._tool({"FILESYSTEM_BASH_ALLOWED_COMMANDS": "echo"})
        r = _run(t.execute({"command": "echo allowed"}))
        self.assertFalse(r.is_error)
        self.assertIn("allowed", r.text)

    def test_empty_command_under_list(self) -> None:
        t = self._tool({"FILESYSTEM_BASH_ALLOWED_COMMANDS": "echo"})
        r = _run(t.execute({"command": "   "}))
        self.assertTrue(r.is_error)
        self.assertIn("bash: command is empty", r.text)


class PathGuardTests(_Base):
    def test_absolute_outside_root_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            tgt = os.path.join(os.path.realpath(outside), "secret")
            t = self._tool()
            r = _run(t.execute({"command": f"cat {tgt}"}))
            self.assertTrue(r.is_error)
            self.assertIn("refusing to execute", r.text)
            self.assertIn("outside the allowed roots", r.text)

    def test_traversal_rejected(self) -> None:
        t = self._tool()
        r = _run(t.execute({"command": "cat ../../etc/passwd"}))
        self.assertTrue(r.is_error)
        self.assertIn("refusing to execute", r.text)

    def test_in_root_path_not_a_false_positive(self) -> None:
        if not _bash_available():
            self.skipTest("no bash shell")
        inside = os.path.join(self.root, "ok.txt")
        with open(inside, "w", encoding="utf-8") as fh:
            fh.write("data")
        t = self._tool()
        r = _run(t.execute({"command": f'cat "{inside}"'}))
        self.assertFalse(r.is_error, r.text)
        self.assertIn("data", r.text)

    def test_guard_disabled(self) -> None:
        if not _bash_available():
            self.skipTest("no bash shell")
        t = self._tool({"FILESYSTEM_BASH_PATH_GUARD": "false"})
        # absolute path outside root would normally be refused; with the
        # guard off it runs (command itself may fail, but not refused).
        r = _run(t.execute({"command": "echo /etc/anything"}))
        self.assertNotIn("refusing to execute", r.text)


class ExecutionTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        if not _bash_available():
            self.skipTest("no bash shell")

    def test_basic_stdout(self) -> None:
        r = _run(self._tool().execute({"command": "echo hello world"}))
        self.assertFalse(r.is_error)
        self.assertIn("hello world", r.text)
        self.assertEqual(r.structured["exit_code"], 0)

    def test_nonzero_exit(self) -> None:
        r = _run(self._tool().execute({"command": "exit 3"}))
        self.assertTrue(r.is_error)
        self.assertEqual(r.structured["exit_code"], 3)
        self.assertIn("[exit code 3]", r.text)

    def test_no_output(self) -> None:
        r = _run(self._tool().execute({"command": "true"}))
        self.assertFalse(r.is_error)
        self.assertEqual(r.text, "(no output)")

    def test_combined_stdout_stderr(self) -> None:
        r = _run(self._tool().execute(
            {"command": "echo out; echo err 1>&2"}
        ))
        self.assertIn("out", r.text)
        self.assertIn("err", r.text)

    def test_timeout(self) -> None:
        with mock.patch.object(bash_tool, "_TIMEOUT_S", 1):
            r = _run(self._tool().execute({"command": "sleep 3"}))
        self.assertTrue(r.is_error)
        self.assertTrue(r.structured["timed_out"])
        self.assertIn("[timed out after 1s]", r.text)

    def test_output_truncated(self) -> None:
        with mock.patch.object(bash_tool, "_MAX_BUFFER", 32):
            r = _run(self._tool().execute(
                {"command": "for i in $(seq 1 200); do echo LINE$i; done"}
            ))
        self.assertTrue(r.is_error)
        self.assertTrue(r.structured["output_truncated"])
        self.assertIn("[Output truncated:", r.text)


if __name__ == "__main__":
    unittest.main()
