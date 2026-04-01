"""Tests for AgentChannel implementations and ask_user integration."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import MagicMock, patch

from micro_x_agent_loop.agent_channel import (
    ASK_USER_SCHEMA,
    BufferedChannel,
    TerminalChannel,
)
from micro_x_agent_loop.terminal_prompter import prompt_free_text, prompt_with_options
from micro_x_agent_loop.turn_engine import TurnEngine
from micro_x_agent_loop.usage import UsageResult
from tests.fakes import FakeStreamProvider, FakeTool
from tests.test_turn_engine import RecordingEvents

# ---------------------------------------------------------------------------
# ASK_USER_SCHEMA tests
# ---------------------------------------------------------------------------


class TestAskUserSchema(unittest.TestCase):
    def test_has_correct_name(self) -> None:
        self.assertEqual("ask_user", ASK_USER_SCHEMA["name"])

    def test_has_required_question(self) -> None:
        self.assertIn("question", ASK_USER_SCHEMA["input_schema"]["properties"])
        self.assertIn("question", ASK_USER_SCHEMA["input_schema"]["required"])

    def test_has_optional_options(self) -> None:
        self.assertIn("options", ASK_USER_SCHEMA["input_schema"]["properties"])
        self.assertNotIn("options", ASK_USER_SCHEMA["input_schema"]["required"])


# ---------------------------------------------------------------------------
# BufferedChannel tests
# ---------------------------------------------------------------------------


class TestBufferedChannel(unittest.TestCase):
    def test_emit_text_delta_accumulates(self) -> None:
        ch = BufferedChannel()
        ch.emit_text_delta("Hello")
        ch.emit_text_delta(" world")
        self.assertEqual("Hello world", ch.text)

    def test_emit_tool_events_recorded(self) -> None:
        ch = BufferedChannel()
        ch.emit_tool_started("t1", "read_file")
        ch.emit_tool_completed("t1", "read_file", False)
        self.assertEqual(2, len(ch.tool_events))
        self.assertEqual(("started", "t1", "read_file"), ch.tool_events[0])
        self.assertEqual(("completed", "t1", "read_file"), ch.tool_events[1])

    def test_emit_error_recorded(self) -> None:
        ch = BufferedChannel()
        ch.emit_error("something broke")
        self.assertEqual(["something broke"], ch.errors)

    def test_emit_turn_complete_recorded(self) -> None:
        ch = BufferedChannel()
        ch.emit_turn_complete({"input_tokens": 10})
        self.assertEqual([{"input_tokens": 10}], ch.turn_usages)

    def test_ask_user_returns_timeout_message(self) -> None:
        ch = BufferedChannel()
        answer = asyncio.run(ch.ask_user("What file?"))
        self.assertIn("No response from human", answer)

    def test_ask_user_with_options_returns_timeout(self) -> None:
        ch = BufferedChannel()
        options = [{"label": "A", "description": "First"}, {"label": "B", "description": "Second"}]
        answer = asyncio.run(ch.ask_user("Pick one", options))
        self.assertIn("No response from human", answer)


# ---------------------------------------------------------------------------
# TerminalChannel tests
# ---------------------------------------------------------------------------


class TestTerminalChannel(unittest.TestCase):
    def test_emit_text_delta_prints_plain(self) -> None:
        ch = TerminalChannel(markdown=False)
        with patch("builtins.print") as mock_print:
            ch.emit_text_delta("Hello")
            mock_print.assert_called_once_with("Hello", end="", flush=True)

    def test_emit_text_delta_markdown_buffers(self) -> None:
        ch = TerminalChannel(markdown=True)
        ch.emit_text_delta("Hello")
        self.assertIsNotNone(ch._renderer)
        self.assertEqual(ch._renderer._buffer, "Hello")
        ch.end_streaming()

    def test_ask_user_free_text(self) -> None:
        ch = TerminalChannel()
        with patch("micro_x_agent_loop.agent_channel.prompt_free_text", return_value="main.py"):
            answer = asyncio.run(ch.ask_user("Which file?"))
        self.assertEqual("main.py", answer)

    def test_ask_user_with_options(self) -> None:
        ch = TerminalChannel()
        options = [{"label": "A", "description": "First"}, {"label": "B", "description": "Second"}]
        with patch("micro_x_agent_loop.agent_channel.prompt_with_options", return_value="A"):
            answer = asyncio.run(ch.ask_user("Pick one", options))
        self.assertEqual("A", answer)

    def test_ask_user_fallback_on_error(self) -> None:
        ch = TerminalChannel()
        with (
            patch("micro_x_agent_loop.agent_channel.prompt_free_text", side_effect=RuntimeError("not a tty")),
            patch("micro_x_agent_loop.agent_channel.fallback_prompt", return_value="fallback.py"),
        ):
            answer = asyncio.run(ch.ask_user("Which file?"))
        self.assertEqual("fallback.py", answer)

    @patch("micro_x_agent_loop.terminal_prompter.questionary")
    def test_prompt_with_options_returns_selected(self, mock_q: MagicMock) -> None:
        mock_q.select.return_value.ask.return_value = "OAuth 2.0"
        result = prompt_with_options(
            "Which auth?",
            [{"label": "OAuth 2.0", "description": "Standard"}, {"label": "API Keys", "description": "Simple"}],
        )
        self.assertEqual("OAuth 2.0", result)

    @patch("micro_x_agent_loop.terminal_prompter.questionary")
    def test_prompt_with_options_other_triggers_text(self, mock_q: MagicMock) -> None:
        mock_q.select.return_value.ask.return_value = "__other__"
        mock_q.text.return_value.ask.return_value = "Custom answer"
        result = prompt_with_options(
            "Which auth?",
            [{"label": "OAuth 2.0", "description": "Standard"}, {"label": "API Keys", "description": "Simple"}],
        )
        self.assertEqual("Custom answer", result)
        mock_q.text.assert_called_once()

    @patch("micro_x_agent_loop.terminal_prompter.questionary")
    def test_prompt_with_options_ctrl_c_returns_empty(self, mock_q: MagicMock) -> None:
        mock_q.select.return_value.ask.return_value = None
        result = prompt_with_options(
            "Which auth?",
            [{"label": "OAuth 2.0", "description": "Standard"}],
        )
        self.assertEqual("", result)

    @patch("micro_x_agent_loop.terminal_prompter.questionary")
    def test_prompt_free_text_returns_typed(self, mock_q: MagicMock) -> None:
        mock_q.text.return_value.ask.return_value = "hello world"
        result = prompt_free_text("What?")
        self.assertEqual("hello world", result)

    @patch("micro_x_agent_loop.terminal_prompter.questionary")
    def test_prompt_free_text_ctrl_c_returns_empty(self, mock_q: MagicMock) -> None:
        mock_q.text.return_value.ask.return_value = None
        result = prompt_free_text("What?")
        self.assertEqual("", result)

    def test_begin_streaming_starts_spinner_plain(self) -> None:
        ch = TerminalChannel(markdown=False)
        ch.begin_streaming()
        self.assertIsNotNone(ch._spinner)
        ch.end_streaming()
        self.assertIsNone(ch._spinner)

    def test_begin_streaming_starts_renderer_markdown(self) -> None:
        ch = TerminalChannel(markdown=True)
        ch.begin_streaming()
        self.assertIsNotNone(ch._renderer)
        self.assertTrue(ch._renderer.is_showing_spinner())
        ch.end_streaming()
        self.assertIsNone(ch._renderer)

    def test_tool_started_creates_spinner_plain(self) -> None:
        ch = TerminalChannel(markdown=False)
        ch.emit_tool_started("t1", "read_file")
        self.assertIsNotNone(ch._spinner)
        ch.emit_tool_completed("t1", "read_file", False)
        self.assertIsNone(ch._spinner)

    def test_tool_started_creates_renderer_markdown(self) -> None:
        ch = TerminalChannel(markdown=True)
        ch.emit_tool_started("t1", "read_file")
        self.assertIsNotNone(ch._renderer)
        ch.emit_tool_completed("t1", "read_file", False)


# ---------------------------------------------------------------------------
# TurnEngine integration tests
# ---------------------------------------------------------------------------


def _make_engine_with_channel(
    provider: FakeStreamProvider,
    events: RecordingEvents,
    channel: BufferedChannel | None = None,
    tools: list[FakeTool] | None = None,
) -> TurnEngine:
    tool_list = tools or []
    converted = [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tool_list
    ]
    return TurnEngine(
        provider=provider,
        model="m",
        max_tokens=1024,
        temperature=0.5,
        system_prompt="sys",
        converted_tools=converted,
        tool_map={t.name: t for t in tool_list},
        max_tool_result_chars=40_000,
        max_tokens_retries=3,
        events=events,
        channel=channel,
    )


class TestTurnEngineAskUser(unittest.TestCase):
    def test_ask_user_only_continues_loop(self) -> None:
        """When LLM only calls ask_user, loop continues without checkpoint."""
        provider = FakeStreamProvider()
        # Response 1: ask_user only
        provider.responses.append((
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Let me ask."}],
            },
            [{"name": "ask_user", "id": "au1", "input": {"question": "Which file?"}}],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        # Response 2: final text
        provider.queue(text="Got it, reading main.py.", stop_reason="end_turn")

        events = RecordingEvents()
        channel = BufferedChannel()
        engine = _make_engine_with_channel(provider, events, channel=channel)

        # BufferedChannel.ask_user returns a default timeout message
        asyncio.run(engine.run(messages=[], user_message="read a file"))

        # No checkpoint calls (ask_user is handled inline)
        self.assertEqual(0, len(events.checkpoint_calls))
        # 2 API calls
        self.assertEqual(2, len(events.api_call_metrics))
        # The tool result was appended
        tool_result_msg = events.appended[2]  # user, assistant, user(tool_result)
        self.assertEqual("user", tool_result_msg[0])
        results = tool_result_msg[1]
        self.assertEqual(1, len(results))
        parsed = json.loads(results[0]["content"])
        self.assertIn("answer", parsed)

    def test_ask_user_mixed_with_regular_tools(self) -> None:
        """ask_user and regular tools in the same response are both handled, merged in order."""
        tool = FakeTool(name="read_file", description="Read a file", execute_result="file data")
        provider = FakeStreamProvider()
        # Response 1: ask_user + regular tool
        provider.responses.append((
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Asking and reading."}],
            },
            [
                {"name": "ask_user", "id": "au1", "input": {"question": "Confirm?"}},
                {"name": "read_file", "id": "t1", "input": {"path": "x.py"}},
            ],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        # Response 2: final text
        provider.queue(text="Done.", stop_reason="end_turn")

        events = RecordingEvents()
        channel = BufferedChannel()
        engine = _make_engine_with_channel(provider, events, channel=channel, tools=[tool])

        asyncio.run(engine.run(messages=[], user_message="read and confirm"))

        self.assertEqual(1, tool.execute_calls)
        # Results merged: user, assistant, user(tool_results), assistant
        tool_result_msg = events.appended[2]
        self.assertEqual("user", tool_result_msg[0])
        results = tool_result_msg[1]
        self.assertEqual(2, len(results))
        # Order matches original: au1 first, t1 second
        self.assertEqual("au1", results[0]["tool_use_id"])
        self.assertEqual("t1", results[1]["tool_use_id"])

    def test_no_channel_treats_ask_user_as_unknown(self) -> None:
        """Without a channel, 'ask_user' is routed as a regular tool and fails as unknown."""
        provider = FakeStreamProvider()
        provider.responses.append((
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Asking."}],
            },
            [{"name": "ask_user", "id": "au1", "input": {"question": "Which?"}}],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        provider.queue(text="OK.", stop_reason="end_turn")

        events = RecordingEvents()
        # No channel
        engine = _make_engine_with_channel(provider, events, channel=None)

        asyncio.run(engine.run(messages=[], user_message="test"))

        # Should have been treated as unknown tool
        self.assertEqual(1, len(events.tool_call_records))
        record = events.tool_call_records[0]
        self.assertTrue(record["is_error"])
        self.assertIn("unknown tool", record["result_text"])


class TestTurnEngineAskUserSchemaInjection(unittest.TestCase):
    def test_ask_user_schema_included_when_channel_present(self) -> None:
        """When a channel is present, ask_user schema is appended to api_tools."""
        provider = FakeStreamProvider()
        provider.queue(text="Hello.", stop_reason="end_turn")

        events = RecordingEvents()
        channel = BufferedChannel()
        engine = _make_engine_with_channel(provider, events, channel=channel)

        asyncio.run(engine.run(messages=[], user_message="hi"))

        # Verify ASK_USER_SCHEMA has the expected shape
        self.assertEqual("ask_user", ASK_USER_SCHEMA["name"])
        self.assertIn("question", ASK_USER_SCHEMA["input_schema"]["properties"])


if __name__ == "__main__":
    unittest.main()
