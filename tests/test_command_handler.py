"""Tests for CommandHandler slash-command logic."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from micro_x_agent_loop.api_payload_store import ApiPayload, ApiPayloadStore
from micro_x_agent_loop.commands.command_handler import CommandHandler
from micro_x_agent_loop.commands.prompt_commands import PromptCommandStore
from micro_x_agent_loop.memory.facade import ActiveMemoryFacade
from micro_x_agent_loop.metrics import SessionAccumulator
from micro_x_agent_loop.services.checkpoint_service import CheckpointService
from micro_x_agent_loop.services.session_controller import SessionController
from micro_x_agent_loop.tool_result_formatter import ToolResultFormatter
from tests.fakes import CheckpointManagerFake, SessionManagerFake


def _make_handler(
    *,
    output: list[str] | None = None,
    tool_map: dict | None = None,
    memory_enabled: bool = False,
    user_memory_enabled: bool = False,
    user_memory_dir: str = "",
    api_payload_store: ApiPayloadStore | None = None,
    voice_runtime=None,
    prompt_commands: dict[str, str] | None = None,
    on_tools_deleted=None,
    tool_result_formatter: ToolResultFormatter | None = None,
) -> tuple[CommandHandler, list[str]]:
    """Build a CommandHandler with minimal mocks. Returns (handler, output_list)."""
    out: list[str] = [] if output is None else output

    # SessionAccumulator
    acc = SessionAccumulator()
    acc.session_id = "s1"

    # Memory facade — real ActiveMemoryFacade wrapping the existing
    # SessionManagerFake and CheckpointManagerFake from tests/fakes.py.
    # The fakes pre-populate "s1" with sensible defaults so most tests
    # don't need any further setup; tests that need a different state
    # (e.g. empty list_sessions) reach into the fake directly.
    session_manager = SessionManagerFake()
    checkpoint_manager = CheckpointManagerFake()
    memory = ActiveMemoryFacade(
        session_manager=session_manager,
        checkpoint_manager=checkpoint_manager,
        event_emitter=None,
        active_session_id="s1",
        store=None,
    )

    # ToolResultFormatter — real instance so per-test format configs land in the
    # actual tool_formatting dict (no more pre-canned mock return_values that
    # tests then assert on, which the original codebase review flagged as
    # tautological).
    formatter = tool_result_formatter or ToolResultFormatter(default_format={"format": "json"})

    # Payload store
    if api_payload_store is None:
        api_payload_store = ApiPayloadStore()

    # PromptCommandStore mock
    if prompt_commands is None:
        prompt_commands = {}
    pcs = MagicMock(spec=PromptCommandStore)
    pcs.list_commands.return_value = [(name, f"desc-{name}") for name in prompt_commands]
    pcs.load_command.side_effect = lambda name: prompt_commands.get(name)

    # SessionController and CheckpointService — both are pure formatters;
    # the real instances let tests assert on the actual rendered text
    # rather than the mock's pre-canned return value.
    sc = SessionController(line_prefix="  ")
    cs = CheckpointService(line_prefix="  ")

    handler = CommandHandler(
        line_prefix="  ",
        session_accumulator=acc,
        memory=memory,
        memory_enabled=memory_enabled,
        tool_map=tool_map or {},
        tool_result_formatter=formatter,
        api_payload_store=api_payload_store,
        voice_runtime=voice_runtime,
        session_controller=sc,
        checkpoint_service=cs,
        user_memory_enabled=user_memory_enabled,
        user_memory_dir=user_memory_dir,
        prompt_command_store=pcs,
        on_session_reset=lambda sid, msgs: None,
        on_tools_deleted=on_tools_deleted,
        output=out.append,
    )
    return handler, out


class HelpTests(unittest.IsolatedAsyncioTestCase):
    async def test_on_help_with_memory_disabled(self) -> None:
        handler, out = _make_handler(memory_enabled=False)
        await handler.on_help()
        combined = "\n".join(out)
        self.assertIn("/help", combined)
        self.assertIn("/cost", combined)
        # Memory section says to enable MemoryEnabled
        self.assertIn("MemoryEnabled=true", combined)

    async def test_on_help_with_memory_enabled(self) -> None:
        handler, out = _make_handler(memory_enabled=True, user_memory_enabled=True)
        await handler.on_help()
        combined = "\n".join(out)
        self.assertIn("/session", combined)
        self.assertIn("/memory", combined)

    def test_on_unknown_command(self) -> None:
        handler, out = _make_handler()
        handler.on_unknown_command("/frobnitz")
        self.assertTrue(any("Unknown local command" in line for line in out))


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_list_when_no_commands(self) -> None:
        handler, out = _make_handler(prompt_commands={})
        await handler.handle_command("/command")
        combined = "\n".join(out)
        self.assertIn("No commands found", combined)

    async def test_command_list_with_commands(self) -> None:
        handler, out = _make_handler(prompt_commands={"greet": "Hello $ARGUMENTS"})
        await handler.handle_command("/command")
        combined = "\n".join(out)
        self.assertIn("greet", combined)

    async def test_command_unknown_name(self) -> None:
        handler, out = _make_handler(prompt_commands={"greet": "Hello"})
        result = await handler.handle_command("/command nonexistent")
        self.assertIsNone(result)
        self.assertTrue(any("Unknown command" in line for line in out))

    async def test_command_returns_prompt_without_args(self) -> None:
        handler, out = _make_handler(prompt_commands={"greet": "Hello $ARGUMENTS"})
        result = await handler.handle_command("/command greet")
        self.assertEqual("Hello ", result)

    async def test_command_returns_prompt_with_args(self) -> None:
        handler, out = _make_handler(prompt_commands={"greet": "Hello $ARGUMENTS"})
        result = await handler.handle_command("/command greet world")
        self.assertEqual("Hello world", result)


class CostTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_cost(self) -> None:
        handler, out = _make_handler()
        await handler.handle_cost("/cost")
        self.assertTrue(len(out) >= 1)


class MemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_memory_disabled(self) -> None:
        handler, out = _make_handler(user_memory_enabled=False)
        await handler.handle_memory("/memory")
        self.assertTrue(any("UserMemoryEnabled" in line for line in out))

    async def test_memory_show_no_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handler, out = _make_handler(user_memory_enabled=True, user_memory_dir=tmp)
            await handler.handle_memory("/memory")
            self.assertTrue(any("No memory file found" in line for line in out))

    async def test_memory_show_with_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "MEMORY.md").write_text("# Memory content", encoding="utf-8")
            handler, out = _make_handler(user_memory_enabled=True, user_memory_dir=tmp)
            await handler.handle_memory("/memory")
            self.assertTrue(any("Memory content" in line for line in out))

    async def test_memory_list_no_dir(self) -> None:
        handler, out = _make_handler(user_memory_enabled=True, user_memory_dir="/nonexistent/dir/xyz")
        await handler.handle_memory("/memory list")
        self.assertTrue(any("No memory files found" in line for line in out))

    async def test_memory_list_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handler, out = _make_handler(user_memory_enabled=True, user_memory_dir=tmp)
            await handler.handle_memory("/memory list")
            self.assertTrue(any("No memory files found" in line for line in out))

    async def test_memory_list_with_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "MEMORY.md").write_text("content", encoding="utf-8")
            Path(tmp, "notes.md").write_text("notes", encoding="utf-8")
            handler, out = _make_handler(user_memory_enabled=True, user_memory_dir=tmp)
            await handler.handle_memory("/memory list")
            combined = "\n".join(out)
            self.assertIn("MEMORY.md", combined)
            self.assertIn("notes.md", combined)

    async def test_memory_edit_no_editor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handler, out = _make_handler(user_memory_enabled=True, user_memory_dir=tmp)
            with patch.dict(os.environ, {}, clear=True):
                # Remove EDITOR and VISUAL from the env
                env = {k: v for k, v in os.environ.items() if k not in ("EDITOR", "VISUAL")}
                with patch.dict(os.environ, env, clear=True):
                    await handler.handle_memory("/memory edit")
            self.assertTrue(any("No $EDITOR" in line for line in out))

    async def test_memory_edit_with_editor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"EDITOR": "nano"}):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = None
                    handler, out = _make_handler(user_memory_enabled=True, user_memory_dir=tmp)
                    await handler.handle_memory("/memory edit")
            self.assertTrue(any("Editor closed" in line for line in out))

    async def test_memory_reset_no_dir(self) -> None:
        handler, out = _make_handler(user_memory_enabled=True, user_memory_dir="/nonexistent/xyz")
        await handler.handle_memory("/memory reset")
        self.assertTrue(any("No memory directory to reset" in line for line in out))

    async def test_memory_reset_no_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handler, out = _make_handler(user_memory_enabled=True, user_memory_dir=tmp)
            await handler.handle_memory("/memory reset")
            self.assertTrue(any("No memory files to reset" in line for line in out))

    async def test_memory_reset_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "MEMORY.md").write_text("x", encoding="utf-8")
            handler, out = _make_handler(user_memory_enabled=True, user_memory_dir=tmp)
            await handler.handle_memory("/memory reset")
            self.assertTrue(any("Run '/memory reset confirm'" in line for line in out))

    async def test_memory_reset_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "MEMORY.md").write_text("x", encoding="utf-8")
            handler, out = _make_handler(user_memory_enabled=True, user_memory_dir=tmp)
            await handler.handle_memory("/memory reset confirm")
            self.assertTrue(any("Deleted" in line for line in out))
            self.assertFalse(Path(tmp, "MEMORY.md").exists())

    async def test_memory_invalid_subcommand(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handler, out = _make_handler(user_memory_enabled=True, user_memory_dir=tmp)
            await handler.handle_memory("/memory bogus")
            self.assertTrue(any("Usage:" in line for line in out))


class ToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_tools_no_subcommand(self) -> None:
        handler, out = _make_handler()
        await handler.handle_tools("/tools")
        self.assertTrue(any("Usage:" in line for line in out))

    async def test_tools_mcp_no_mcp_tools(self) -> None:
        from tests.fakes import FakeTool

        # Only built-in tool (no __) — should show "No MCP tools loaded."
        handler, out = _make_handler(tool_map={"ask_user": FakeTool("ask_user")})
        await handler.handle_tools("/tools mcp")
        self.assertTrue(any("No MCP tools loaded" in line for line in out))

    async def test_tools_mcp_with_tools(self) -> None:
        from tests.fakes import FakeTool

        handler, out = _make_handler(
            tool_map={
                "server1__read_file": FakeTool("server1__read_file"),
                "server1__write_file": FakeTool("server1__write_file"),
                "server2__search": FakeTool("server2__search"),
            }
        )
        await handler.handle_tools("/tools mcp")
        combined = "\n".join(out)
        self.assertIn("server1", combined)
        self.assertIn("server2", combined)


class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_list_empty(self) -> None:
        handler, out = _make_handler(tool_map={})
        await handler.handle_tool("/tool")
        self.assertTrue(any("No tools loaded" in line for line in out))

    async def test_tool_list_with_tools(self) -> None:
        from tests.fakes import FakeTool

        handler, out = _make_handler(
            tool_map={
                "server__foo": FakeTool("server__foo"),
                "ask_user": FakeTool("ask_user"),
            }
        )
        await handler.handle_tool("/tool")
        combined = "\n".join(out)
        self.assertIn("server", combined)
        self.assertIn("(built-in)", combined)

    async def test_tool_details(self) -> None:
        from tests.fakes import FakeTool

        tool = FakeTool("server__foo", description="does things")
        handler, out = _make_handler(tool_map={"server__foo": tool})
        await handler.handle_tool("/tool server__foo")
        combined = "\n".join(out)
        self.assertIn("server__foo", combined)
        self.assertIn("does things", combined)

    async def test_tool_by_short_name(self) -> None:
        from tests.fakes import FakeTool

        tool = FakeTool("server__foo", description="short")
        handler, out = _make_handler(tool_map={"server__foo": tool})
        await handler.handle_tool("/tool foo")
        combined = "\n".join(out)
        self.assertIn("server__foo", combined)

    async def test_tool_ambiguous(self) -> None:
        from tests.fakes import FakeTool

        handler, out = _make_handler(
            tool_map={
                "s1__foo": FakeTool("s1__foo"),
                "s2__foo": FakeTool("s2__foo"),
            }
        )
        await handler.handle_tool("/tool foo")
        self.assertTrue(any("Ambiguous" in line for line in out))

    async def test_tool_not_found(self) -> None:
        handler, out = _make_handler(tool_map={})
        await handler.handle_tool("/tool nonexistent")
        self.assertTrue(any("not found" in line for line in out))

    async def test_tool_schema(self) -> None:
        from tests.fakes import FakeTool

        tool = FakeTool("server__foo", input_schema={"type": "object", "properties": {}})
        handler, out = _make_handler(tool_map={"server__foo": tool})
        await handler.handle_tool("/tool server__foo schema")
        self.assertTrue(any("Input schema" in line for line in out))

    async def test_tool_config_default(self) -> None:
        from tests.fakes import FakeTool

        tool = FakeTool("server__foo")
        handler, out = _make_handler(tool_map={"server__foo": tool})
        await handler.handle_tool("/tool server__foo config")
        combined = "\n".join(out)
        self.assertIn("default", combined)

    async def test_tool_config_custom(self) -> None:
        from tests.fakes import FakeTool

        tool = FakeTool("server__foo")
        # Wire a real ToolFormatting config for this tool — the real
        # ToolResultFormatter reads it and the handler prints the result.
        formatter = ToolResultFormatter(
            tool_formatting={"server__foo": {"strategy": "table"}},
            default_format={"format": "json"},
        )
        handler, out = _make_handler(
            tool_map={"server__foo": tool},
            tool_result_formatter=formatter,
        )
        await handler.handle_tool("/tool server__foo config")
        combined = "\n".join(out)
        self.assertIn("table", combined)

    async def test_tool_invalid_sub(self) -> None:
        from tests.fakes import FakeTool

        tool = FakeTool("server__foo")
        handler, out = _make_handler(tool_map={"server__foo": tool})
        await handler.handle_tool("/tool server__foo bogus")
        self.assertTrue(any("Usage:" in line for line in out))

    async def test_tool_delete_generated_task(self) -> None:
        from tests.fakes import FakeTool

        deleted: list[list[str]] = []
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            task_dir = project_root / "tools" / "email_summary"
            task_dir.mkdir(parents=True)
            manifest_path = project_root / "tools" / "manifest.json"
            manifest_path.write_text(
                """{
  "email_summary": {
    "tool_name": "email_summary",
    "server": {
      "cwd": "tools/email_summary/"
    }
  }
}
""",
                encoding="utf-8",
            )

            handler, out = _make_handler(
                tool_map={"email_summary__email_summary": FakeTool("email_summary__email_summary")},
                on_tools_deleted=deleted.append,
            )

            # The handler resolves the manifest via Path.cwd(); contain the
            # chdir inside the TemporaryDirectory so the test still works in
            # parallel and never writes inside the repo.
            original_cwd = Path.cwd()
            os.chdir(project_root)
            try:
                await handler.handle_tool("/tool delete email_summary")
            finally:
                os.chdir(original_cwd)

            self.assertFalse(task_dir.exists())
            self.assertEqual("{}", manifest_path.read_text(encoding="utf-8").strip())
            self.assertNotIn("email_summary__email_summary", handler._tool_map)
            self.assertEqual([["email_summary__email_summary"]], deleted)
            self.assertTrue(any("Deleted generated task: email_summary" in line for line in out))

    async def test_tool_delete_generated_task_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            manifest_dir = project_root / "tools"
            manifest_dir.mkdir(parents=True)
            (manifest_dir / "manifest.json").write_text("{}", encoding="utf-8")

            handler, out = _make_handler()
            original_cwd = Path.cwd()
            os.chdir(project_root)
            try:
                await handler.handle_tool("/tool delete missing_task")
            finally:
                os.chdir(original_cwd)

            self.assertTrue(any("Generated task not found: missing_task" in line for line in out))


class DebugTests(unittest.IsolatedAsyncioTestCase):
    async def test_debug_no_subcommand(self) -> None:
        handler, out = _make_handler()
        await handler.handle_debug("/debug")
        self.assertTrue(any("Usage:" in line for line in out))

    async def test_debug_show_api_payload_empty(self) -> None:
        handler, out = _make_handler()
        await handler.handle_debug("/debug show-api-payload")
        self.assertTrue(any("No API payloads recorded" in line for line in out))

    async def test_debug_show_api_payload_out_of_range(self) -> None:
        store = ApiPayloadStore()
        store.record(
            ApiPayload(
                timestamp=0.0,
                model="claude",
                system_prompt="sys",
                messages=[{"role": "user", "content": "hello"}],
                tools_count=0,
                response_message={"role": "assistant", "content": "hi"},
                stop_reason="end_turn",
                usage=None,
            )
        )
        handler, out = _make_handler(api_payload_store=store)
        await handler.handle_debug("/debug show-api-payload 99")
        self.assertTrue(any("out of range" in line for line in out))

    async def test_debug_show_api_payload_ok(self) -> None:
        store = ApiPayloadStore()
        from micro_x_agent_loop.usage import UsageResult

        store.record(
            ApiPayload(
                timestamp=0.0,
                model="claude-3-5",
                system_prompt="You are helpful." * 5,
                messages=[{"role": "user", "content": "hello"}],
                tools_count=3,
                response_message={"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
                stop_reason="end_turn",
                usage=UsageResult(
                    provider="anthropic",
                    model="claude-3-5",
                    input_tokens=100,
                    output_tokens=50,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                    message_count=1,
                    tool_schema_count=0,
                    stop_reason="end_turn",
                    duration_ms=100,
                    time_to_first_token_ms=None,
                ),
            )
        )
        handler, out = _make_handler(api_payload_store=store)
        await handler.handle_debug("/debug show-api-payload")
        combined = "\n".join(out)
        self.assertIn("claude-3-5", combined)

    async def test_debug_show_api_payload_invalid_index(self) -> None:
        handler, out = _make_handler()
        await handler.handle_debug("/debug show-api-payload notanint")
        self.assertTrue(any("Usage:" in line for line in out))


class ConsoleLogLevelTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_consumer(self) -> None:
        handler, out = _make_handler()
        with patch("micro_x_agent_loop.logging_config.ConsoleLogConsumer.get_instance", return_value=None):
            await handler.handle_console_log_level("/console-log-level")
        self.assertTrue(any("No console log consumer" in line for line in out))

    async def test_show_level(self) -> None:
        consumer = MagicMock()
        consumer.level = "DEBUG"
        handler, out = _make_handler()
        with patch("micro_x_agent_loop.logging_config.ConsoleLogConsumer.get_instance", return_value=consumer):
            await handler.handle_console_log_level("/console-log-level")
        self.assertTrue(any("DEBUG" in line for line in out))

    async def test_set_valid_level(self) -> None:
        consumer = MagicMock()
        consumer.level = "INFO"
        handler, out = _make_handler()
        with patch("micro_x_agent_loop.logging_config.ConsoleLogConsumer.get_instance", return_value=consumer):
            await handler.handle_console_log_level("/console-log-level DEBUG")
        consumer.set_level.assert_called_once_with("DEBUG")
        self.assertTrue(any("DEBUG" in line for line in out))

    async def test_set_invalid_level(self) -> None:
        consumer = MagicMock()
        handler, out = _make_handler()
        with patch("micro_x_agent_loop.logging_config.ConsoleLogConsumer.get_instance", return_value=consumer):
            await handler.handle_console_log_level("/console-log-level BOGUS")
        consumer.set_level.assert_not_called()
        self.assertTrue(any("Invalid level" in line for line in out))


class VoiceCommandTests(unittest.IsolatedAsyncioTestCase):
    """Tests for /voice subcommands."""

    def _make_with_voice(self) -> tuple[CommandHandler, list[str], object]:
        voice_runtime = MagicMock()
        voice_runtime.start = AsyncMock(return_value="Voice started")
        voice_runtime.stop = AsyncMock(return_value="Voice stopped")
        voice_runtime.status = AsyncMock(return_value="Voice running")
        voice_runtime.devices = AsyncMock(return_value="Mic, Loopback")
        voice_runtime.events = AsyncMock(return_value="event1\nevent2")
        handler, out = _make_handler(voice_runtime=voice_runtime)
        return handler, out, voice_runtime

    async def test_voice_no_subcommand(self) -> None:
        handler, out, _ = self._make_with_voice()
        await handler.handle_voice("/voice")
        self.assertTrue(any("Usage:" in line for line in out))

    async def test_voice_start(self) -> None:
        handler, out, vr = self._make_with_voice()
        await handler.handle_voice("/voice start")
        vr.start.assert_called_once()
        self.assertTrue(any("Voice started" in line for line in out))

    async def test_voice_start_with_source(self) -> None:
        handler, out, vr = self._make_with_voice()
        await handler.handle_voice("/voice start loopback")
        call_args = vr.start.call_args[0]
        self.assertEqual("loopback", call_args[0])

    async def test_voice_start_parse_error(self) -> None:
        handler, out, vr = self._make_with_voice()
        await handler.handle_voice("/voice start --chunk-seconds notanint")
        self.assertTrue(any("chunk-seconds" in line for line in out))
        vr.start.assert_not_called()

    async def test_voice_status(self) -> None:
        handler, out, vr = self._make_with_voice()
        await handler.handle_voice("/voice status")
        vr.status.assert_called_once()
        self.assertTrue(any("Voice running" in line for line in out))

    async def test_voice_devices(self) -> None:
        handler, out, vr = self._make_with_voice()
        await handler.handle_voice("/voice devices")
        vr.devices.assert_called_once()
        self.assertTrue(any("Mic" in line for line in out))

    async def test_voice_events(self) -> None:
        handler, out, vr = self._make_with_voice()
        await handler.handle_voice("/voice events")
        vr.events.assert_called_once()

    async def test_voice_events_with_limit(self) -> None:
        handler, out, vr = self._make_with_voice()
        await handler.handle_voice("/voice events 10")
        vr.events.assert_called_once_with(10)

    async def test_voice_events_invalid_limit(self) -> None:
        handler, out, vr = self._make_with_voice()
        await handler.handle_voice("/voice events notanint")
        self.assertTrue(any("Usage:" in line for line in out))
        vr.events.assert_not_called()

    async def test_voice_stop(self) -> None:
        handler, out, vr = self._make_with_voice()
        await handler.handle_voice("/voice stop")
        vr.stop.assert_called_once()
        self.assertTrue(any("Voice stopped" in line for line in out))

    async def test_voice_unknown_action(self) -> None:
        handler, out, vr = self._make_with_voice()
        await handler.handle_voice("/voice bogus")
        self.assertTrue(any("Usage:" in line for line in out))

    async def test_voice_invalid_syntax(self) -> None:
        handler, out, vr = self._make_with_voice()
        # Unterminated quote causes shlex.split to raise
        await handler.handle_voice('/voice "unclosed')
        self.assertTrue(any("Invalid command syntax" in line for line in out))


class SessionCommandTests(unittest.IsolatedAsyncioTestCase):
    """Tests for /session subcommands requiring memory_enabled=True.

    Drives SessionManagerFake (from tests/fakes.py) directly rather than
    asserting against a MagicMock's pre-canned return values — assertions
    exercise the real command-handler formatting code path.
    """

    def _make_with_memory(self) -> tuple[CommandHandler, list[str], SessionManagerFake]:
        handler, out = _make_handler(memory_enabled=True)
        return handler, out, handler._memory.session_manager  # type: ignore[return-value]

    async def test_session_memory_disabled(self) -> None:
        handler, out = _make_handler(memory_enabled=False)
        await handler.handle_session("/session")
        self.assertTrue(any("MemoryEnabled" in line for line in out))

    async def test_session_show_current(self) -> None:
        handler, out, _ = self._make_with_memory()
        await handler.handle_session("/session")
        combined = "\n".join(out)
        # SessionManagerFake pre-populates s1 with title "Session One"
        self.assertIn("Current session: Session One", combined)

    async def test_session_list(self) -> None:
        handler, out, _ = self._make_with_memory()
        await handler.handle_session("/session list")
        combined = "\n".join(out)
        self.assertIn("Recent sessions", combined)
        self.assertIn("Session One", combined)

    async def test_session_list_with_limit(self) -> None:
        handler, out, sm = self._make_with_memory()
        # Pre-populate more sessions and verify limit truncates output.
        # SessionManagerFake.create_session always returns the same id;
        # add them by writing directly into its _sessions dict.
        for i in range(2, 8):
            sm._sessions[f"s{i}"] = {
                "id": f"s{i}",
                "title": f"Session {i}",
                "parent_session_id": None,
                "created_at": "2026-02-19T00:00:00+00:00",
                "updated_at": "2026-02-19T00:00:00+00:00",
                "status": "active",
            }
        await handler.handle_session("/session list 3")
        # Session list-entry lines contain "(id=", so count those.
        listed = sum(1 for line in out if "(id=" in line)
        self.assertEqual(3, listed)

    async def test_session_list_invalid_limit(self) -> None:
        handler, out, _ = self._make_with_memory()
        await handler.handle_session("/session list notanint")
        self.assertTrue(any("Usage:" in line for line in out))

    async def test_session_list_empty(self) -> None:
        handler, out, sm = self._make_with_memory()
        # Empty the fake's session store directly.
        sm._sessions.clear()
        await handler.handle_session("/session list")
        self.assertTrue(any("No sessions found" in line for line in out))

    async def test_session_new(self) -> None:
        handler, out, _ = self._make_with_memory()
        await handler.handle_session("/session new My Title")
        combined = "\n".join(out)
        self.assertIn("Started new session", combined)

    async def test_session_name(self) -> None:
        handler, out, sm = self._make_with_memory()
        await handler.handle_session("/session name My New Title")
        combined = "\n".join(out)
        self.assertIn("Session named", combined)
        # The fake's session store was actually mutated — verify the title.
        self.assertEqual("My New Title", sm.get_session("s1")["title"])

    async def test_session_name_no_active(self) -> None:
        handler, out, _ = self._make_with_memory()
        handler._memory.active_session_id = None
        await handler.handle_session("/session name foo")
        self.assertTrue(any("No active session" in line for line in out))

    async def test_session_name_empty(self) -> None:
        handler, out, _ = self._make_with_memory()
        await handler.handle_session("/session name")
        self.assertTrue(any("Usage:" in line for line in out))

    async def test_session_resume(self) -> None:
        handler, out, _ = self._make_with_memory()
        await handler.handle_session("/session resume s1")
        combined = "\n".join(out)
        self.assertIn("Resumed session", combined)

    async def test_session_resume_not_found(self) -> None:
        handler, out, _ = self._make_with_memory()
        await handler.handle_session("/session resume nonexistent")
        self.assertTrue(any("not found" in line for line in out))

    async def test_session_resume_error(self) -> None:
        handler, out, _ = self._make_with_memory()
        # SessionManagerFake.resolve_session_identifier raises ValueError
        # for the identifier "ambiguous" — a real error path, not a mock.
        await handler.handle_session("/session resume ambiguous")
        self.assertTrue(any("ambiguous" in line for line in out))

    async def test_session_fork(self) -> None:
        handler, out, _ = self._make_with_memory()
        await handler.handle_session("/session fork")
        combined = "\n".join(out)
        self.assertIn("Forked session", combined)

    async def test_session_fork_no_active(self) -> None:
        handler, out, _ = self._make_with_memory()
        handler._memory.active_session_id = None
        await handler.handle_session("/session fork")
        self.assertTrue(any("No active session" in line for line in out))

    async def test_session_unknown_sub(self) -> None:
        handler, out, _ = self._make_with_memory()
        await handler.handle_session("/session bogus")
        self.assertTrue(any("Usage:" in line for line in out))


class RewindCommandTests(unittest.IsolatedAsyncioTestCase):
    """Drives CheckpointManagerFake instead of pre-canned MagicMock returns."""

    def _make_with_memory(self) -> tuple[CommandHandler, list[str], CheckpointManagerFake]:
        handler, out = _make_handler(memory_enabled=True)
        return handler, out, handler._memory.checkpoint_manager  # type: ignore[return-value]

    async def test_rewind_memory_disabled(self) -> None:
        handler, out = _make_handler(memory_enabled=False)
        await handler.handle_rewind("/rewind cp1")
        self.assertTrue(any("MemoryEnabled" in line for line in out))

    async def test_rewind_usage(self) -> None:
        handler, out, _ = self._make_with_memory()
        await handler.handle_rewind("/rewind")
        self.assertTrue(any("Usage:" in line for line in out))

    async def test_rewind_success(self) -> None:
        handler, out, cm = self._make_with_memory()
        await handler.handle_rewind("/rewind cp1")
        # CheckpointManagerFake records the call in .rewinds and the real
        # CheckpointService formats the outcome — assert on both observable
        # effects instead of a mock's call_args.
        self.assertEqual(["cp1"], cm.rewinds)
        self.assertTrue(any("Rewind cp1 results" in line for line in out))

    async def test_rewind_error(self) -> None:
        handler, out, cm = self._make_with_memory()
        # Replace the fake's rewind_files with a function that raises so
        # the error path is exercised end-to-end.
        cm.rewind_files = lambda _cid: (_ for _ in ()).throw(RuntimeError("bad checkpoint"))  # type: ignore[assignment]
        await handler.handle_rewind("/rewind cp-bad")
        self.assertTrue(any("Rewind failed" in line for line in out))


class CheckpointCommandTests(unittest.IsolatedAsyncioTestCase):
    """Drives CheckpointManagerFake instead of pre-canned MagicMock returns."""

    def _make_with_memory(self) -> tuple[CommandHandler, list[str], CheckpointManagerFake]:
        handler, out = _make_handler(memory_enabled=True)
        return handler, out, handler._memory.checkpoint_manager  # type: ignore[return-value]

    async def test_checkpoint_memory_disabled(self) -> None:
        handler, out = _make_handler(memory_enabled=False)
        await handler.handle_checkpoint("/checkpoint list")
        self.assertTrue(any("MemoryEnabled" in line for line in out))

    async def test_checkpoint_list(self) -> None:
        handler, out, _ = self._make_with_memory()
        await handler.handle_checkpoint("/checkpoint list")
        combined = "\n".join(out)
        self.assertIn("Recent checkpoints", combined)

    async def test_checkpoint_list_empty(self) -> None:
        handler, out, cm = self._make_with_memory()
        cm.list_checkpoints = lambda *_a, **_kw: []  # type: ignore[assignment]
        await handler.handle_checkpoint("/checkpoint list")
        self.assertTrue(any("No checkpoints found" in line for line in out))

    async def test_checkpoint_list_invalid_limit(self) -> None:
        handler, out, _ = self._make_with_memory()
        await handler.handle_checkpoint("/checkpoint list notanint")
        self.assertTrue(any("Usage:" in line for line in out))

    async def test_checkpoint_rewind(self) -> None:
        handler, out, cm = self._make_with_memory()
        await handler.handle_checkpoint("/checkpoint rewind cp1")
        # Real CheckpointManagerFake records the rewind in .rewinds.
        self.assertEqual(["cp1"], cm.rewinds)

    async def test_checkpoint_unknown_sub(self) -> None:
        handler, out, _ = self._make_with_memory()
        await handler.handle_checkpoint("/checkpoint bogus")
        self.assertTrue(any("Usage:" in line for line in out))


if __name__ == "__main__":
    unittest.main()
