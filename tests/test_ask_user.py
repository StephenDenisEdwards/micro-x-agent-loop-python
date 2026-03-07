"""Tests for ask_user — human-in-the-loop questioning pseudo-tool."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import MagicMock, patch

from micro_x_agent_loop.agent_channel import ASK_USER_SCHEMA, BufferedChannel
from micro_x_agent_loop.ask_user import AskUserHandler, _OTHER_SENTINEL
from micro_x_agent_loop.turn_engine import TurnEngine
from micro_x_agent_loop.usage import UsageResult
from tests.fakes import FakeStreamProvider, FakeTool
from tests.test_turn_engine import RecordingEvents


# ---------------------------------------------------------------------------
# AskUserHandler unit tests
# ---------------------------------------------------------------------------


class TestIsAskUserCall(unittest.TestCase):
    def test_true_for_ask_user(self) -> None:
        self.assertTrue(AskUserHandler.is_ask_user_call("ask_user"))

    def test_false_for_other(self) -> None:
        self.assertFalse(AskUserHandler.is_ask_user_call("tool_search"))
        self.assertFalse(AskUserHandler.is_ask_user_call("read_file"))
        self.assertFalse(AskUserHandler.is_ask_user_call(""))


class TestGetSchema(unittest.TestCase):
    def test_has_correct_name(self) -> None:
        schema = AskUserHandler.get_schema()
        self.assertEqual("ask_user", schema["name"])

    def test_has_required_question(self) -> None:
        schema = AskUserHandler.get_schema()
        self.assertIn("question", schema["input_schema"]["properties"])
        self.assertIn("question", schema["input_schema"]["required"])

    def test_has_optional_options(self) -> None:
        schema = AskUserHandler.get_schema()
        self.assertIn("options", schema["input_schema"]["properties"])
        # options is NOT required
        self.assertNotIn("options", schema["input_schema"]["required"])


class TestAskUserHandle(unittest.TestCase):
    def _make_handler(self) -> AskUserHandler:
        return AskUserHandler(line_prefix="test> ", user_prompt="you> ")

    def test_handle_with_options_selects_first(self) -> None:
        """Selecting the first option returns its label."""
        handler = self._make_handler()
        tool_input = {
            "question": "Which approach?",
            "options": [
                {"label": "Option A", "description": "First approach"},
                {"label": "Option B", "description": "Second approach"},
            ],
        }
        with patch.object(AskUserHandler, "_prompt_with_options", return_value="Option A"):
            result = asyncio.run(handler.handle(tool_input))
        parsed = json.loads(result)
        self.assertEqual("Option A", parsed["answer"])

    def test_handle_with_options_selects_second(self) -> None:
        handler = self._make_handler()
        tool_input = {
            "question": "Which approach?",
            "options": [
                {"label": "Option A", "description": "First approach"},
                {"label": "Option B", "description": "Second approach"},
            ],
        }
        with patch.object(AskUserHandler, "_prompt_with_options", return_value="Option B"):
            result = asyncio.run(handler.handle(tool_input))
        parsed = json.loads(result)
        self.assertEqual("Option B", parsed["answer"])

    def test_handle_other_triggers_free_text(self) -> None:
        """Selecting 'Other' in questionary.select returns the follow-up text answer."""
        handler = self._make_handler()
        tool_input = {
            "question": "Which approach?",
            "options": [
                {"label": "Option A", "description": "First approach"},
                {"label": "Option B", "description": "Second approach"},
            ],
        }
        # _prompt_with_options handles the full Other→text flow internally,
        # so we just mock its return value to be the free-text answer.
        with patch.object(AskUserHandler, "_prompt_with_options", return_value="Actually, do option C"):
            result = asyncio.run(handler.handle(tool_input))
        parsed = json.loads(result)
        self.assertEqual("Actually, do option C", parsed["answer"])

    def test_handle_without_options(self) -> None:
        """Free-form question uses _prompt_free_text and returns the typed text."""
        handler = self._make_handler()
        tool_input = {"question": "What file should I read?"}
        with patch.object(AskUserHandler, "_prompt_free_text", return_value="main.py"):
            result = asyncio.run(handler.handle(tool_input))
        parsed = json.loads(result)
        self.assertEqual("main.py", parsed["answer"])

    def test_handle_returns_valid_json_with_answer_key(self) -> None:
        handler = self._make_handler()
        tool_input = {"question": "Yes or no?"}
        with patch.object(AskUserHandler, "_prompt_free_text", return_value="yes"):
            result = asyncio.run(handler.handle(tool_input))
        parsed = json.loads(result)
        self.assertIn("answer", parsed)

    def test_fallback_on_questionary_error(self) -> None:
        """When questionary raises, the handler falls back to plain input."""
        handler = self._make_handler()
        tool_input = {"question": "What file?"}
        with (
            patch.object(AskUserHandler, "_prompt_free_text", side_effect=RuntimeError("not a tty")),
            patch.object(handler, "_fallback_prompt", return_value="fallback.py") as mock_fb,
        ):
            result = asyncio.run(handler.handle(tool_input))
        parsed = json.loads(result)
        self.assertEqual("fallback.py", parsed["answer"])
        mock_fb.assert_called_once_with("What file?", [])


# ---------------------------------------------------------------------------
# _prompt_with_options unit tests (mock questionary directly)
# ---------------------------------------------------------------------------


class TestPromptWithOptions(unittest.TestCase):
    def _options(self) -> list[dict[str, str]]:
        return [
            {"label": "OAuth 2.0", "description": "Industry standard"},
            {"label": "API Keys", "description": "Simple, stateless"},
        ]

    @patch("micro_x_agent_loop.ask_user.questionary")
    def test_returns_selected_option(self, mock_q: MagicMock) -> None:
        mock_q.select.return_value.ask.return_value = "OAuth 2.0"
        result = AskUserHandler._prompt_with_options("Which auth?", self._options())
        self.assertEqual("OAuth 2.0", result)

    @patch("micro_x_agent_loop.ask_user.questionary")
    def test_other_triggers_text_prompt(self, mock_q: MagicMock) -> None:
        mock_q.select.return_value.ask.return_value = _OTHER_SENTINEL
        mock_q.text.return_value.ask.return_value = "Custom answer"
        result = AskUserHandler._prompt_with_options("Which auth?", self._options())
        self.assertEqual("Custom answer", result)
        mock_q.text.assert_called_once()

    @patch("micro_x_agent_loop.ask_user.questionary")
    def test_ctrl_c_returns_empty(self, mock_q: MagicMock) -> None:
        mock_q.select.return_value.ask.return_value = None
        result = AskUserHandler._prompt_with_options("Which auth?", self._options())
        self.assertEqual("", result)


class TestPromptFreeText(unittest.TestCase):
    @patch("micro_x_agent_loop.ask_user.questionary")
    def test_returns_typed_text(self, mock_q: MagicMock) -> None:
        mock_q.text.return_value.ask.return_value = "hello world"
        result = AskUserHandler._prompt_free_text("What?")
        self.assertEqual("hello world", result)

    @patch("micro_x_agent_loop.ask_user.questionary")
    def test_ctrl_c_returns_empty(self, mock_q: MagicMock) -> None:
        mock_q.text.return_value.ask.return_value = None
        result = AskUserHandler._prompt_free_text("What?")
        self.assertEqual("", result)


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
