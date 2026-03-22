import asyncio
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from micro_x_agent_loop.agent import Agent
from micro_x_agent_loop.agent_channel import BufferedChannel
from micro_x_agent_loop.agent_config import AgentConfig
from micro_x_agent_loop.usage import UsageResult
from tests.fakes import (
    CheckpointManagerFake,
    FakeEventEmitter,
    FakeMcpTool,
    FakeTool,
    SessionManagerFake,
)


class AgentCommandTests(unittest.TestCase):
    def _make_agent(self) -> Agent:
        return Agent(
            AgentConfig(
                api_key="test",
                tools=[FakeTool()],
                memory_enabled=True,
                session_id="s1",
                session_manager=SessionManagerFake(),
                checkpoint_manager=CheckpointManagerFake(),
                event_emitter=FakeEventEmitter(),
                channel=BufferedChannel(),
            )
        )

    def test_help_includes_new_commands(self) -> None:
        agent = self._make_agent()
        asyncio.run(agent._handle_local_command("/help"))
        out = agent._channel.text
        self.assertIn("/session new [title]", out)
        self.assertIn("/checkpoint list [limit]", out)
        self.assertIn("/cost", out)

    def test_unknown_local_command_message(self) -> None:
        agent = self._make_agent()
        asyncio.run(agent._handle_local_command("/unknown"))
        self.assertIn("Unknown local command", agent._channel.text)

    def test_session_new_and_name(self) -> None:
        agent = self._make_agent()
        asyncio.run(agent._handle_session_command("/session new Planning"))
        asyncio.run(agent._handle_session_command("/session name Planning Updated"))
        out = agent._channel.text
        self.assertIn("Started new session:", out)
        self.assertIn("Session named: Planning Updated", out)

    def test_session_resume_by_name_prints_summary(self) -> None:
        agent = self._make_agent()
        asyncio.run(agent._handle_session_command("/session resume Session One"))
        out = agent._channel.text
        self.assertIn("Resumed session Session One", out)
        self.assertIn("Session summary:", out)

    def test_session_resume_not_found_and_ambiguous(self) -> None:
        agent = self._make_agent()
        asyncio.run(agent._handle_session_command("/session resume missing"))
        asyncio.run(agent._handle_session_command("/session resume ambiguous"))
        out = agent._channel.text
        self.assertIn("Session not found: missing", out)
        self.assertIn("ambiguous", out)

    def test_session_fork_updates_active(self) -> None:
        agent = self._make_agent()
        asyncio.run(agent._handle_session_command("/session fork"))
        out = agent._channel.text
        self.assertIn("Forked session s1 -> s-fork", out)

    def test_checkpoint_list_and_rewind_alias(self) -> None:
        agent = self._make_agent()
        asyncio.run(agent._handle_checkpoint_command("/checkpoint list"))
        asyncio.run(agent._handle_checkpoint_command("/checkpoint rewind cp1"))
        out = agent._channel.text
        self.assertIn("Recent checkpoints:", out)
        self.assertIn("Rewind cp1 results:", out)

    def test_checkpoint_usage_error_and_rewind_usage(self) -> None:
        agent = self._make_agent()
        asyncio.run(agent._handle_checkpoint_command("/checkpoint list x"))
        asyncio.run(agent._handle_rewind_command("/rewind"))
        out = agent._channel.text
        self.assertIn("Usage: /checkpoint list [limit]", out)
        self.assertIn("Usage: /rewind <checkpoint_id>", out)

    def test_run_handles_max_tokens_retry_then_stop(self) -> None:
        agent = self._make_agent()
        stream_result = (
            {"role": "assistant", "content": [{"type": "text", "text": "cut"}]},
            [],
            "max_tokens",
            UsageResult(),
        )
        with patch.object(agent._provider, "stream_chat", side_effect=[stream_result] * 3):
            asyncio.run(agent.run("hello"))
            errors = agent._channel.errors
            self.assertTrue(
                any("Stopped: response exceeded max_tokens" in e for e in errors),
                f"Expected max_tokens error in channel errors, got: {errors}",
            )

    def test_cost_command_prints_summary(self) -> None:
        agent = self._make_agent()
        asyncio.run(agent._handle_cost_command("/cost"))
        out = agent._channel.text
        self.assertIn("Session Cost Summary", out)
        self.assertIn("Total API calls:", out)
        self.assertIn("Total cost:", out)


class ToolCommandTests(unittest.TestCase):
    """Tests for the /tool introspection command."""

    def _make_agent(
        self,
        tools: list | None = None,
        tool_formatting: dict | None = None,
        default_format: dict | None = None,
    ) -> Agent:
        if tools is None:
            tools = [
                FakeMcpTool(
                    name="filesystem__bash",
                    description="Run a shell command",
                    input_schema={"type": "object", "properties": {"cmd": {"type": "string"}}},
                    output_schema={"type": "object", "properties": {"stdout": {"type": "string"}}},
                    is_mutating=True,
                ),
                FakeMcpTool(
                    name="filesystem__read_file",
                    description="Read a file",
                    input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
                    is_mutating=False,
                ),
                FakeMcpTool(
                    name="git__bash",
                    description="Run git bash",
                    input_schema={"type": "object"},
                    is_mutating=True,
                ),
            ]
        kwargs = {}
        if tool_formatting is not None:
            kwargs["tool_formatting"] = tool_formatting
        if default_format is not None:
            kwargs["default_format"] = default_format
        return Agent(AgentConfig(api_key="test", tools=tools, **kwargs))

    def _run(self, agent: Agent, command: str) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_local_command(command))
        return buf.getvalue()

    # -- /tool (list) --

    def test_tool_list_groups_by_server(self) -> None:
        out = self._run(self._make_agent(), "/tool")
        self.assertIn("[filesystem]", out)
        self.assertIn("[git]", out)
        self.assertIn("bash", out)
        self.assertIn("read_file", out)

    def test_tool_list_empty(self) -> None:
        out = self._run(self._make_agent(tools=[]), "/tool")
        self.assertIn("No tools loaded", out)

    def test_tool_list_builtin_group(self) -> None:
        out = self._run(self._make_agent(tools=[FakeTool(name="noop")]), "/tool")
        self.assertIn("(built-in)", out)
        self.assertIn("noop", out)

    # -- /tool <name> (details) --

    def test_tool_details_by_full_name(self) -> None:
        out = self._run(self._make_agent(), "/tool filesystem__bash")
        self.assertIn("Name: filesystem__bash", out)
        self.assertIn("Description: Run a shell command", out)
        self.assertIn("Mutating: True", out)

    def test_tool_details_by_short_name(self) -> None:
        out = self._run(self._make_agent(), "/tool read_file")
        self.assertIn("Name: filesystem__read_file", out)
        self.assertIn("Description: Read a file", out)
        self.assertIn("Mutating: False", out)

    def test_tool_not_found(self) -> None:
        out = self._run(self._make_agent(), "/tool nonexistent")
        self.assertIn("Tool not found: nonexistent", out)

    def test_tool_ambiguous_short_name(self) -> None:
        out = self._run(self._make_agent(), "/tool bash")
        self.assertIn("Ambiguous tool name 'bash'", out)
        self.assertIn("filesystem__bash", out)
        self.assertIn("git__bash", out)

    # -- /tool <name> schema --

    def test_tool_schema_shows_input_and_output(self) -> None:
        out = self._run(self._make_agent(), "/tool filesystem__bash schema")
        self.assertIn("Input schema:", out)
        self.assertIn('"cmd"', out)
        self.assertIn("Output schema:", out)
        self.assertIn('"stdout"', out)

    def test_tool_schema_no_output_schema(self) -> None:
        out = self._run(self._make_agent(), "/tool read_file schema")
        self.assertIn("Input schema:", out)
        self.assertNotIn("Output schema:", out)

    # -- /tool <name> config --

    def test_tool_config_shows_specific(self) -> None:
        formatting = {"filesystem__bash": {"format": "text", "field": "stdout"}}
        agent = self._make_agent(tool_formatting=formatting)
        out = self._run(agent, "/tool filesystem__bash config")
        self.assertIn("ToolFormatting config for filesystem__bash:", out)
        self.assertIn('"format": "text"', out)
        self.assertNotIn("using default", out)

    def test_tool_config_shows_default(self) -> None:
        agent = self._make_agent()
        out = self._run(agent, "/tool filesystem__bash config")
        self.assertIn("(using default)", out)
        self.assertIn('"format": "json"', out)

    # -- /help includes /tool --

    def test_help_includes_tool_commands(self) -> None:
        agent = self._make_agent()
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_local_command("/help"))
        out = buf.getvalue()
        self.assertIn("/tool", out)
        self.assertIn("/tool <name>", out)
        self.assertIn("/tool <name> schema", out)
        self.assertIn("/tool <name> config", out)
        self.assertIn("/tool delete <name>", out)


class DebugCommandTests(unittest.TestCase):
    """Tests for the /debug command."""

    def _make_agent(self) -> Agent:
        return Agent(AgentConfig(api_key="test", tools=[FakeTool()]))

    def _run(self, agent: Agent, command: str) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_local_command(command))
        return buf.getvalue()

    def test_debug_no_payloads(self) -> None:
        out = self._run(self._make_agent(), "/debug show-api-payload")
        self.assertIn("No API payloads recorded yet", out)

    def test_debug_show_payload(self) -> None:
        import time

        from micro_x_agent_loop.api_payload_store import ApiPayload

        agent = self._make_agent()
        agent._api_payload_store.record(ApiPayload(
            timestamp=time.time(),
            model="claude-haiku-4-5-20251001",
            system_prompt="You are a helpful assistant.",
            messages=[
                {"role": "user", "content": "list files"},
            ],
            tools_count=59,
            response_message={
                "role": "assistant",
                "content": [{"type": "text", "text": "Let me list the files."}],
            },
            stop_reason="tool_use",
            usage=UsageResult(
                input_tokens=24417, output_tokens=68,
                cache_read_input_tokens=11993,
            ),
        ))
        out = self._run(agent, "/debug show-api-payload")
        self.assertIn("API Payload #0 (most recent):", out)
        self.assertIn("claude-haiku-4-5-20251001", out)
        self.assertIn("Messages:     1", out)
        self.assertIn("Tools:        59", out)
        self.assertIn("tool_use", out)
        self.assertIn("in=24417", out)
        self.assertIn("cache_read=11993", out)
        self.assertIn("list files", out)

    def test_debug_skips_tool_result_for_last_user_msg(self) -> None:
        import time

        from micro_x_agent_loop.api_payload_store import ApiPayload

        agent = self._make_agent()
        agent._api_payload_store.record(ApiPayload(
            timestamp=time.time(),
            model="m",
            system_prompt="sys",
            messages=[
                {"role": "user", "content": "list files"},
                {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "bash", "input": {}}]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "file1.txt"}]},
            ],
            tools_count=5,
            response_message={"role": "assistant", "content": [{"type": "text", "text": "Done."}]},
            stop_reason="end_turn",
            usage=UsageResult(input_tokens=100, output_tokens=10),
        ))
        out = self._run(agent, "/debug show-api-payload")
        # Should show the original user message, not the tool_result
        self.assertIn("list files", out)

    def test_debug_shows_tool_names_in_response(self) -> None:
        import time

        from micro_x_agent_loop.api_payload_store import ApiPayload

        agent = self._make_agent()
        agent._api_payload_store.record(ApiPayload(
            timestamp=time.time(),
            model="m",
            system_prompt="sys",
            messages=[{"role": "user", "content": "read a.py"}],
            tools_count=5,
            response_message={
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "a.py"}}],
            },
            stop_reason="tool_use",
            usage=UsageResult(input_tokens=100, output_tokens=10),
        ))
        out = self._run(agent, "/debug show-api-payload")
        self.assertIn("tool_use: read_file", out)

    def test_debug_show_payload_out_of_range(self) -> None:
        import time

        from micro_x_agent_loop.api_payload_store import ApiPayload

        agent = self._make_agent()
        agent._api_payload_store.record(ApiPayload(
            timestamp=time.time(),
            model="m",
            system_prompt="sys",
            messages=[],
            tools_count=0,
            response_message=None,
            stop_reason="end_turn",
            usage=None,
        ))
        out = self._run(agent, "/debug show-api-payload 5")
        self.assertIn("out of range", out)

    def test_debug_usage_message(self) -> None:
        out = self._run(self._make_agent(), "/debug")
        self.assertIn("Usage:", out)
        self.assertIn("show-api-payload", out)

    def test_help_includes_debug_command(self) -> None:
        agent = self._make_agent()
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_local_command("/help"))
        out = buf.getvalue()
        self.assertIn("/debug show-api-payload", out)


if __name__ == "__main__":
    unittest.main()
