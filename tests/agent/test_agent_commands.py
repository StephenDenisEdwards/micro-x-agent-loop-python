import asyncio
import io
import unittest
from contextlib import redirect_stdout
from typing import Any
from unittest.mock import patch

from micro_x_agent_loop.agent import Agent
from micro_x_agent_loop.agent_config import AgentConfig
from micro_x_agent_loop.usage import UsageResult
from tests.fakes import FakeEventEmitter, FakeMcpTool, FakeTool


class _SessionManagerFake:
    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {
            "s1": {
                "id": "s1",
                "title": "Session One",
                "parent_session_id": None,
                "created_at": "2026-02-19T00:00:00+00:00",
                "updated_at": "2026-02-19T00:00:00+00:00",
                "status": "active",
            }
        }
        self._messages: dict[str, list[dict]] = {"s1": []}

    def load_messages(self, session_id: str) -> list[dict]:
        return list(self._messages.get(session_id, []))

    def get_session(self, session_id: str) -> dict | None:
        return self._sessions.get(session_id)

    def list_sessions(self, limit: int = 20) -> list[dict]:
        return list(self._sessions.values())[:limit]

    def create_session(self, title: str | None = None, **_: Any) -> str:
        sid = "s-new"
        self._sessions[sid] = {
            "id": sid,
            "title": title or "Session New",
            "parent_session_id": None,
            "created_at": "2026-02-19T01:00:00+00:00",
            "updated_at": "2026-02-19T01:00:00+00:00",
            "status": "active",
        }
        self._messages[sid] = []
        return sid

    def set_session_title(self, session_id: str, title: str) -> None:
        self._sessions[session_id]["title"] = title

    def resolve_session_identifier(self, identifier: str) -> dict | None:
        identifier = identifier.strip()
        if identifier == "ambiguous":
            raise ValueError("ambiguous")
        if identifier in self._sessions:
            return self._sessions[identifier]
        for session in self._sessions.values():
            if session["title"].casefold() == identifier.casefold():
                return session
        return None

    def build_session_summary(self, session_id: str) -> dict:
        return {
            "session_id": session_id,
            "title": self._sessions[session_id]["title"],
            "created_at": "2026-02-19T00:00:00+00:00",
            "updated_at": "2026-02-19T00:10:00+00:00",
            "message_count": 2,
            "user_message_count": 1,
            "assistant_message_count": 1,
            "checkpoint_count": 1,
            "last_user_preview": "hello",
            "last_assistant_preview": "world",
        }

    def fork_session(self, source_session_id: str) -> str:
        sid = "s-fork"
        self._sessions[sid] = {
            "id": sid,
            "title": "Fork Session",
            "parent_session_id": source_session_id,
            "created_at": "2026-02-19T02:00:00+00:00",
            "updated_at": "2026-02-19T02:00:00+00:00",
            "status": "active",
        }
        self._messages[sid] = []
        return sid

    def append_message(self, session_id: str, role: str, content: str | list[dict]) -> tuple[str, int]:
        msgs = self._messages.setdefault(session_id, [])
        msgs.append({"role": role, "content": content})
        return f"m{len(msgs)}", len(msgs)

    def record_tool_call(self, *args: Any, **kwargs: Any) -> str:
        return "tc1"


class _CheckpointManagerFake:
    enabled = True
    write_tools_only = True

    def __init__(self) -> None:
        self.created: list[str] = []
        self.rewinds: list[str] = []

    def create_checkpoint(self, session_id: str, user_message_id: str, scope: dict | None = None) -> str:
        cid = "cp1"
        self.created.append(cid)
        return cid

    def maybe_track_tool_input(self, checkpoint_id: str, tool_input: dict) -> list[str]:
        return []

    def list_checkpoints(self, session_id: str, limit: int = 20) -> list[dict]:
        return [
            {
                "id": "cp1",
                "created_at": "2026-02-19T00:05:00+00:00",
                "tools": ["write_file"],
                "user_preview": "update file",
            }
        ]

    def rewind_files(self, checkpoint_id: str) -> tuple[str, list[dict[str, str]]]:
        self.rewinds.append(checkpoint_id)
        return "s1", [{"path": "x.txt", "status": "restored", "detail": ""}]


class AgentCommandTests(unittest.TestCase):
    def _make_agent(self) -> Agent:
        return Agent(
            AgentConfig(
                api_key="test",
                tools=[FakeTool()],
                memory_enabled=True,
                session_id="s1",
                session_manager=_SessionManagerFake(),
                checkpoint_manager=_CheckpointManagerFake(),
                event_emitter=FakeEventEmitter(),
            )
        )

    def test_help_includes_new_commands(self) -> None:
        agent = self._make_agent()
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_local_command("/help"))
        out = buf.getvalue()
        self.assertIn("/session new [title]", out)
        self.assertIn("/checkpoint list [limit]", out)
        self.assertIn("/cost", out)

    def test_unknown_local_command_message(self) -> None:
        agent = self._make_agent()
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_local_command("/unknown"))
        self.assertIn("Unknown local command", buf.getvalue())

    def test_session_new_and_name(self) -> None:
        agent = self._make_agent()
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_session_command("/session new Planning"))
            asyncio.run(agent._handle_session_command("/session name Planning Updated"))
        out = buf.getvalue()
        self.assertIn("Started new session:", out)
        self.assertIn("Session named: Planning Updated", out)

    def test_session_resume_by_name_prints_summary(self) -> None:
        agent = self._make_agent()
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_session_command("/session resume Session One"))
        out = buf.getvalue()
        self.assertIn("Resumed session Session One", out)
        self.assertIn("Session summary:", out)

    def test_session_resume_not_found_and_ambiguous(self) -> None:
        agent = self._make_agent()
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_session_command("/session resume missing"))
            asyncio.run(agent._handle_session_command("/session resume ambiguous"))
        out = buf.getvalue()
        self.assertIn("Session not found: missing", out)
        self.assertIn("ambiguous", out)

    def test_session_fork_updates_active(self) -> None:
        agent = self._make_agent()
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_session_command("/session fork"))
        out = buf.getvalue()
        self.assertIn("Forked session s1 -> s-fork", out)

    def test_checkpoint_list_and_rewind_alias(self) -> None:
        agent = self._make_agent()
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_checkpoint_command("/checkpoint list"))
            asyncio.run(agent._handle_checkpoint_command("/checkpoint rewind cp1"))
        out = buf.getvalue()
        self.assertIn("Recent checkpoints:", out)
        self.assertIn("Rewind cp1 results:", out)

    def test_checkpoint_usage_error_and_rewind_usage(self) -> None:
        agent = self._make_agent()
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_checkpoint_command("/checkpoint list x"))
            asyncio.run(agent._handle_rewind_command("/rewind"))
        out = buf.getvalue()
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
            buf = io.StringIO()
            with redirect_stdout(buf):
                asyncio.run(agent.run("hello"))
            out = buf.getvalue()
            self.assertIn("Stopped: response exceeded max_tokens", out)

    def test_cost_command_prints_summary(self) -> None:
        agent = self._make_agent()
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent._handle_cost_command("/cost"))
        out = buf.getvalue()
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


if __name__ == "__main__":
    unittest.main()
