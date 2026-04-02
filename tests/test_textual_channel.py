"""Tests for the Textual TUI channel."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import MagicMock


class TextualChannelTests(unittest.TestCase):
    """Unit tests for TextualChannel — verifies it delegates to the app."""

    def setUp(self) -> None:
        self.mock_app = MagicMock()

        from micro_x_agent_loop.tui.channel import TextualChannel

        self.channel = TextualChannel(self.mock_app)

    def test_emit_text_delta(self) -> None:
        self.channel.emit_text_delta("hello")
        self.mock_app.on_text_delta.assert_called_once_with("hello")

    def test_emit_tool_started(self) -> None:
        self.channel.emit_tool_started("id-1", "read_file")
        self.mock_app.on_tool_started.assert_called_once_with("id-1", "read_file")

    def test_emit_tool_completed(self) -> None:
        self.channel.emit_tool_completed("id-1", "read_file", False)
        self.mock_app.on_tool_completed.assert_called_once_with("id-1", "read_file", False)

    def test_emit_tool_completed_error(self) -> None:
        self.channel.emit_tool_completed("id-1", "read_file", True)
        self.mock_app.on_tool_completed.assert_called_once_with("id-1", "read_file", True)

    def test_emit_turn_complete(self) -> None:
        usage: dict[str, Any] = {"tokens": 100}
        self.channel.emit_turn_complete(usage)
        self.mock_app.on_turn_complete.assert_called_once_with(usage)

    def test_emit_error(self) -> None:
        self.channel.emit_error("something broke")
        self.mock_app.on_agent_error.assert_called_once_with("something broke")

    def test_emit_system_message(self) -> None:
        self.channel.emit_system_message("system info")
        self.mock_app.on_system_message.assert_called_once_with("system info")

    def test_begin_streaming(self) -> None:
        self.channel.begin_streaming()
        self.mock_app.on_begin_streaming.assert_called_once()

    def test_end_streaming(self) -> None:
        self.channel.end_streaming()
        self.mock_app.on_end_streaming.assert_called_once()

    def test_ask_user_resolves_future(self) -> None:
        """ask_user should pass the future to the app and await it."""

        def mock_on_ask_user(
            question: str,
            options: list[dict[str, str]] | None,
            fut: asyncio.Future[str],
        ) -> None:
            fut.set_result("user said yes")

        self.mock_app.on_ask_user = mock_on_ask_user

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(self.channel.ask_user("Continue?"))
            self.assertEqual(result, "user said yes")
        finally:
            loop.close()

    def test_ask_user_with_options(self) -> None:
        captured_options: list[Any] = []

        def mock_on_ask_user(
            question: str,
            options: list[dict[str, str]] | None,
            fut: asyncio.Future[str],
        ) -> None:
            captured_options.append(options)
            fut.set_result("option A")

        self.mock_app.on_ask_user = mock_on_ask_user

        options = [{"label": "A", "description": "First"}, {"label": "B", "description": "Second"}]
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(self.channel.ask_user("Pick one", options))
            self.assertEqual(result, "option A")
            self.assertEqual(captured_options[0], options)
        finally:
            loop.close()


class CliArgParsingTests(unittest.TestCase):
    """Test that --tui flag is parsed correctly."""

    def test_tui_flag_parsed(self) -> None:
        import sys
        original_argv = sys.argv
        try:
            sys.argv = ["prog", "--tui"]
            from micro_x_agent_loop.__main__ import _parse_cli_args

            args = _parse_cli_args()
            self.assertTrue(args["tui"])
        finally:
            sys.argv = original_argv

    def test_tui_flag_default_false(self) -> None:
        import sys
        original_argv = sys.argv
        try:
            sys.argv = ["prog"]
            from micro_x_agent_loop.__main__ import _parse_cli_args

            args = _parse_cli_args()
            self.assertFalse(args["tui"])
        finally:
            sys.argv = original_argv

    def test_tui_with_config(self) -> None:
        import sys
        original_argv = sys.argv
        try:
            sys.argv = ["prog", "--config", "my.json", "--tui"]
            from micro_x_agent_loop.__main__ import _parse_cli_args

            args = _parse_cli_args()
            self.assertTrue(args["tui"])
            self.assertEqual(args["config"], "my.json")
        finally:
            sys.argv = original_argv


if __name__ == "__main__":
    unittest.main()
