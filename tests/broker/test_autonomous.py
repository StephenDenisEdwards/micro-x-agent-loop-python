"""Tests for autonomous mode configuration."""

from __future__ import annotations

import unittest

from micro_x_agent_loop.system_prompt import get_system_prompt


class AutonomousModeTests(unittest.TestCase):
    def test_autonomous_directive_added_when_enabled(self) -> None:
        prompt = get_system_prompt(autonomous=True)
        self.assertIn("Autonomous Mode", prompt)
        self.assertIn("ask_user", prompt)

    def test_autonomous_directive_absent_by_default(self) -> None:
        prompt = get_system_prompt()
        self.assertNotIn("Autonomous Mode", prompt)

    def test_autonomous_mode_no_ask_user_without_channel(self) -> None:
        """When autonomous=True with no channel, ask_user directive is absent."""
        from micro_x_agent_loop.agent import Agent
        from micro_x_agent_loop.agent_config import AgentConfig

        config = AgentConfig(
            model="test-model",
            api_key="test-key",
            autonomous=True,
        )
        agent = Agent(config)
        self.assertIsNone(agent._channel)
        self.assertTrue(agent._autonomous)

    def test_interactive_mode_includes_ask_user(self) -> None:
        """When a channel is provided, ask_user directive is included."""
        from micro_x_agent_loop.agent import Agent
        from micro_x_agent_loop.agent_channel import BufferedChannel
        from micro_x_agent_loop.agent_config import AgentConfig

        config = AgentConfig(
            model="test-model",
            api_key="test-key",
            autonomous=False,
            channel=BufferedChannel(),
        )
        agent = Agent(config)
        self.assertIsNotNone(agent._channel)
        self.assertFalse(agent._autonomous)


class CliArgParsingTests(unittest.TestCase):
    def test_parse_run_flag(self) -> None:
        import sys
        original = sys.argv
        try:
            sys.argv = ["prog", "--run", "hello world"]
            from micro_x_agent_loop.__main__ import _parse_cli_args
            args = _parse_cli_args()
            self.assertEqual(args["run"], "hello world")
        finally:
            sys.argv = original

    def test_parse_run_with_session(self) -> None:
        import sys
        original = sys.argv
        try:
            sys.argv = ["prog", "--run", "hello", "--session", "abc123"]
            from micro_x_agent_loop.__main__ import _parse_cli_args
            args = _parse_cli_args()
            self.assertEqual(args["run"], "hello")
            self.assertEqual(args["session"], "abc123")
        finally:
            sys.argv = original

    def test_parse_broker_command(self) -> None:
        import sys
        original = sys.argv
        try:
            sys.argv = ["prog", "--broker", "start"]
            from micro_x_agent_loop.__main__ import _parse_cli_args
            args = _parse_cli_args()
            self.assertEqual(args["broker"], ["start"])
        finally:
            sys.argv = original

    def test_parse_job_command(self) -> None:
        import sys
        original = sys.argv
        try:
            sys.argv = ["prog", "--job", "add", "test", "* * * * *", "hello"]
            from micro_x_agent_loop.__main__ import _parse_cli_args
            args = _parse_cli_args()
            self.assertEqual(args["job"], ["add", "test", "* * * * *", "hello"])
        finally:
            sys.argv = original


if __name__ == "__main__":
    unittest.main()
