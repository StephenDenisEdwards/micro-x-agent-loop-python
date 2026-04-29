"""Tests for AgentChannel implementations."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from micro_x_agent_loop.agent_channel import BrokerChannel, BufferedChannel, TerminalChannel

# ---------------------------------------------------------------------------
# BufferedChannel (already has some coverage, just ensure key paths)
# ---------------------------------------------------------------------------


class BufferedChannelTests(unittest.TestCase):
    def test_emit_text_delta(self) -> None:
        ch = BufferedChannel()
        ch.emit_text_delta("hello ")
        ch.emit_text_delta("world")
        self.assertEqual("hello world", ch.text)

    def test_emit_tool_events(self) -> None:
        ch = BufferedChannel()
        ch.emit_tool_started("id1", "search")
        ch.emit_tool_completed("id1", "search", False)
        self.assertEqual(2, len(ch.tool_events))

    def test_emit_error(self) -> None:
        ch = BufferedChannel()
        ch.emit_error("boom")
        self.assertIn("boom", ch.errors)

    def test_emit_system_message(self) -> None:
        ch = BufferedChannel()
        ch.emit_system_message("system info")
        self.assertIn("system info", ch.text)

    def test_emit_turn_complete(self) -> None:
        ch = BufferedChannel()
        ch.emit_turn_complete({"cost": 0.01})
        self.assertEqual(1, len(ch.turn_usages))

    def test_ask_user_returns_timeout(self) -> None:
        ch = BufferedChannel()
        answer = asyncio.run(ch.ask_user("proceed?"))
        self.assertIn("timed out", answer)


# ---------------------------------------------------------------------------
# TerminalChannel with markdown=False (no rich involvement)
# ---------------------------------------------------------------------------


class TerminalChannelPlainTests(unittest.TestCase):
    """Test TerminalChannel with markdown=False (plain output, no rich.Live)."""

    def _make_channel(self) -> TerminalChannel:
        return TerminalChannel(markdown=False)

    def test_emit_text_delta_plain(self) -> None:
        ch = self._make_channel()
        # Should print without errors
        with patch("builtins.print") as mock_print:
            ch.emit_text_delta("hello")
            mock_print.assert_called_once()

    def test_emit_text_delta_stops_spinner(self) -> None:
        ch = self._make_channel()
        # Start a spinner manually
        from micro_x_agent_loop.terminal_renderer import PlainSpinner as _Spinner

        spinner = MagicMock(spec=_Spinner)
        ch._spinner = spinner
        with patch("builtins.print"):
            ch.emit_text_delta("hi")
        spinner.stop.assert_called_once()
        self.assertIsNone(ch._spinner)

    def test_emit_tool_started_starts_spinner(self) -> None:
        ch = self._make_channel()
        with patch("micro_x_agent_loop.agent_channel.PlainSpinner") as MockSpinner:
            instance = MagicMock()
            MockSpinner.return_value = instance
            ch.emit_tool_started("id1", "search")
            instance.start.assert_called_once()

    def test_emit_tool_completed_stops_spinner(self) -> None:
        ch = self._make_channel()
        spinner = MagicMock()
        ch._spinner = spinner
        ch.emit_tool_completed("id1", "search", False)
        spinner.stop.assert_called_once()
        self.assertIsNone(ch._spinner)

    def test_emit_turn_complete_resets_flag(self) -> None:
        ch = self._make_channel()
        ch._first_delta_in_turn = False
        spinner = MagicMock()
        ch._spinner = spinner
        ch.emit_turn_complete({})
        self.assertTrue(ch._first_delta_in_turn)

    def test_emit_error_plain(self) -> None:
        ch = self._make_channel()
        with patch("builtins.print") as mock_print:
            ch.emit_error("something failed")
            mock_print.assert_called()
            args = str(mock_print.call_args)
            self.assertIn("Error", args)

    def test_emit_system_message(self) -> None:
        ch = self._make_channel()
        with patch("builtins.print") as mock_print:
            ch.emit_system_message("system text")
            mock_print.assert_called()

    def test_print_line_with_spinner(self) -> None:
        ch = self._make_channel()
        spinner = MagicMock()
        ch._spinner = spinner
        ch.print_line("through spinner")
        spinner.print_line.assert_called_once_with("through spinner")

    def test_print_line_without_spinner(self) -> None:
        ch = self._make_channel()
        with patch("builtins.print") as mock_print:
            ch.print_line("direct print")
            mock_print.assert_called_with("direct print", flush=True)

    def test_begin_and_end_streaming_plain(self) -> None:
        ch = self._make_channel()
        with patch("micro_x_agent_loop.agent_channel.PlainSpinner") as MockSpinner:
            instance = MagicMock()
            MockSpinner.return_value = instance
            ch.begin_streaming()
            instance.start.assert_called_once()
            ch.end_streaming()
            instance.stop.assert_called_once()


# ---------------------------------------------------------------------------
# TerminalChannel with markdown=True (rich renderer paths)
# ---------------------------------------------------------------------------


class TerminalChannelMarkdownTests(unittest.TestCase):
    """Test TerminalChannel with markdown=True — render paths."""

    def _make_channel(self) -> TerminalChannel:
        return TerminalChannel(markdown=True)

    def test_emit_text_delta_calls_renderer(self) -> None:
        ch = self._make_channel()
        renderer = MagicMock()
        renderer.is_showing_spinner.return_value = False
        ch._renderer = renderer
        ch.emit_text_delta("hello")
        renderer.append_text.assert_called_once_with("hello")

    def test_emit_tool_completed_stops_renderer_spinner(self) -> None:
        ch = self._make_channel()
        renderer = MagicMock()
        ch._renderer = renderer
        ch.emit_tool_completed("id1", "search", False)
        renderer.stop_spinner.assert_called_once()

    def test_emit_turn_complete_stops_renderer(self) -> None:
        ch = self._make_channel()
        renderer = MagicMock()
        ch._renderer = renderer
        ch.emit_turn_complete({"cost": 0.01})
        renderer.finalize_text.assert_called_once()
        renderer.stop.assert_called_once()
        self.assertIsNone(ch._renderer)

    def test_emit_error_stops_renderer(self) -> None:
        ch = self._make_channel()
        renderer = MagicMock()
        ch._renderer = renderer
        with patch("micro_x_agent_loop.terminal_renderer.Console"):
            ch.emit_error("failure")
        renderer.stop.assert_called_once()
        self.assertIsNone(ch._renderer)

    def test_ask_user_stops_renderer(self) -> None:
        ch = self._make_channel()
        renderer = MagicMock()
        ch._renderer = renderer

        async def go():
            with patch("asyncio.to_thread", new_callable=AsyncMock, return_value="answer"):
                result = await ch.ask_user("proceed?")
            return result

        result = asyncio.run(go())
        renderer.finalize_text.assert_called()
        renderer.stop.assert_called()
        self.assertEqual("answer", result)


# ---------------------------------------------------------------------------
# BrokerChannel
# ---------------------------------------------------------------------------


class BrokerChannelTests(unittest.TestCase):
    def _make_channel(self) -> BrokerChannel:
        return BrokerChannel("http://localhost:8321", "run-123", timeout=300, poll_interval=1)

    def test_all_emit_methods_noop(self) -> None:
        ch = self._make_channel()
        ch.emit_text_delta("x")
        ch.emit_tool_started("id", "tool")
        ch.emit_tool_completed("id", "tool", False)
        ch.emit_turn_complete({})
        ch.emit_error("err")
        ch.emit_system_message("msg")
        # No assertions — just should not raise

    def test_ask_user_posts_and_polls_answered(self) -> None:
        async def go():
            ch = self._make_channel()

            # Mock httpx.AsyncClient
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)

            # POST returns question_id
            post_resp = MagicMock()
            post_resp.is_success = True
            post_resp.json.return_value = {"question_id": "qid-1"}
            mock_client.post = AsyncMock(return_value=post_resp)

            # GET polls: first pending, then answered
            get_resp_pending = MagicMock()
            get_resp_pending.is_success = True
            get_resp_pending.json.return_value = {"status": "pending"}

            get_resp_answered = MagicMock()
            get_resp_answered.is_success = True
            get_resp_answered.json.return_value = {"status": "answered", "answer": "yes"}

            mock_client.get = AsyncMock(side_effect=[get_resp_pending, get_resp_answered])

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await ch.ask_user("Proceed?")

            self.assertEqual("yes", result)

        asyncio.run(go())

    def test_ask_user_post_fails(self) -> None:
        async def go():
            ch = self._make_channel()

            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)

            post_resp = MagicMock()
            post_resp.is_success = False
            post_resp.status_code = 503
            mock_client.post = AsyncMock(return_value=post_resp)

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await ch.ask_user("Proceed?")

            self.assertIn("timed out", result)

        asyncio.run(go())

    def test_ask_user_post_exception(self) -> None:
        async def go():
            ch = self._make_channel()

            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=RuntimeError("connection refused"))

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await ch.ask_user("Question?")

            self.assertIn("timed out", result)

        asyncio.run(go())

    def test_ask_user_timed_out_by_server(self) -> None:
        async def go():
            ch = BrokerChannel("http://localhost:8321", "run-1", timeout=1, poll_interval=1)

            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)

            post_resp = MagicMock()
            post_resp.is_success = True
            post_resp.json.return_value = {"question_id": "qid-1"}
            mock_client.post = AsyncMock(return_value=post_resp)

            get_resp = MagicMock()
            get_resp.is_success = True
            get_resp.json.return_value = {"status": "timed_out"}
            mock_client.get = AsyncMock(return_value=get_resp)

            with patch("httpx.AsyncClient", return_value=mock_client):
                with patch("asyncio.sleep", AsyncMock()):
                    result = await ch.ask_user("Q?")

            self.assertIn("timed out", result)

        asyncio.run(go())

    def test_ask_user_with_options(self) -> None:
        async def go():
            ch = self._make_channel()

            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)

            post_resp = MagicMock()
            post_resp.is_success = True
            post_resp.json.return_value = {"question_id": "qid-opts"}
            mock_client.post = AsyncMock(return_value=post_resp)

            get_resp = MagicMock()
            get_resp.is_success = True
            get_resp.json.return_value = {"status": "answered", "answer": "yes"}
            mock_client.get = AsyncMock(return_value=get_resp)

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await ch.ask_user(
                    "Proceed?",
                    options=[
                        {"label": "yes", "description": "Go ahead"},
                        {"label": "no", "description": "Stop"},
                    ],
                )

            self.assertEqual("yes", result)

        asyncio.run(go())


# ---------------------------------------------------------------------------
# _Spinner
# ---------------------------------------------------------------------------


class SpinnerTests(unittest.TestCase):
    def test_start_stop(self) -> None:
        from micro_x_agent_loop.terminal_renderer import PlainSpinner as _Spinner

        spinner = _Spinner(prefix="", label=" Thinking...")
        spinner.start()
        import time

        time.sleep(0.05)
        spinner.stop()

    def test_stop_idempotent(self) -> None:
        from micro_x_agent_loop.terminal_renderer import PlainSpinner as _Spinner

        spinner = _Spinner()
        spinner.start()
        spinner.stop()
        spinner.stop()  # Should not raise

    def test_print_line(self) -> None:
        from micro_x_agent_loop.terminal_renderer import PlainSpinner as _Spinner

        spinner = _Spinner()
        spinner.start()
        spinner.print_line("test line")
        spinner.stop()


# ---------------------------------------------------------------------------
# _RichRenderer
# ---------------------------------------------------------------------------


class RichRendererTests(unittest.TestCase):
    def _make(self):
        from micro_x_agent_loop.terminal_renderer import RichRenderer as _RichRenderer

        return _RichRenderer(line_prefix="  ")

    def test_start_spinner(self) -> None:
        renderer = self._make()
        with patch("micro_x_agent_loop.terminal_renderer.Live") as MockLive:
            instance = MagicMock()
            MockLive.return_value = instance
            renderer.start_spinner()
            instance.start.assert_called_once()
            self.assertTrue(renderer.is_showing_spinner())

    def test_stop_spinner(self) -> None:
        renderer = self._make()
        with patch("micro_x_agent_loop.terminal_renderer.Live") as MockLive:
            live_instance = MagicMock()
            MockLive.return_value = live_instance
            renderer.start_spinner()
            renderer.stop_spinner()
            self.assertFalse(renderer.is_showing_spinner())

    def test_switch_to_markdown(self) -> None:
        renderer = self._make()
        with patch("micro_x_agent_loop.terminal_renderer.Live") as MockLive:
            live_instance = MagicMock()
            MockLive.return_value = live_instance
            renderer.start_spinner()
            renderer.switch_to_markdown()
            self.assertFalse(renderer.is_showing_spinner())

    def test_append_text(self) -> None:
        renderer = self._make()
        with patch("micro_x_agent_loop.terminal_renderer.Live") as MockLive:
            live_instance = MagicMock()
            MockLive.return_value = live_instance
            renderer.switch_to_markdown()
            renderer.append_text("hello ")
            renderer.append_text("world")
            live_instance.update.assert_called()

    def test_finalize_text_empty(self) -> None:
        renderer = self._make()
        # Empty buffer — should not raise or print
        with patch("micro_x_agent_loop.terminal_renderer.Live"):
            renderer.finalize_text()  # No-op when buffer is empty

    def test_finalize_text_with_content(self) -> None:
        renderer = self._make()
        with patch("micro_x_agent_loop.terminal_renderer.Live") as MockLive:
            live_instance = MagicMock()
            MockLive.return_value = live_instance
            renderer.switch_to_markdown()
            renderer.append_text("## Heading")
            renderer.finalize_text()
            # Should have stopped live and printed
            self.assertEqual("", renderer._buffer)

    def test_print_line(self) -> None:
        renderer = self._make()
        with patch("micro_x_agent_loop.terminal_renderer.Live"):
            renderer.print_line("a line")  # Should not raise

    def test_stop(self) -> None:
        renderer = self._make()
        with patch("micro_x_agent_loop.terminal_renderer.Live") as MockLive:
            live_instance = MagicMock()
            MockLive.return_value = live_instance
            renderer.start_spinner()
            renderer.stop()
            self.assertFalse(renderer.is_showing_spinner())
            self.assertEqual("", renderer._buffer)

    def test_stop_live_with_exception(self) -> None:
        """Errors from live.stop() are swallowed."""
        renderer = self._make()
        with patch("micro_x_agent_loop.terminal_renderer.Live") as MockLive:
            live_instance = MagicMock()
            live_instance.stop.side_effect = RuntimeError("terminal error")
            MockLive.return_value = live_instance
            renderer.start_spinner()
            renderer._stop_live()  # Should not raise


# ---------------------------------------------------------------------------
# TerminalChannel _fallback_prompt
# ---------------------------------------------------------------------------


class TerminalChannelFallbackPromptTests(unittest.TestCase):
    def test_fallback_prompt_free_text(self) -> None:
        from micro_x_agent_loop.terminal_prompter import fallback_prompt

        with patch("builtins.input", return_value="my answer"):
            result = fallback_prompt("What is your name?", [])
        self.assertEqual("my answer", result)

    def test_fallback_prompt_with_options_numeric(self) -> None:
        from micro_x_agent_loop.terminal_prompter import fallback_prompt

        options = [
            {"label": "yes", "description": "Go ahead"},
            {"label": "no", "description": "Stop"},
        ]
        with patch("builtins.input", return_value="1"):
            with patch("builtins.print"):
                result = fallback_prompt("Proceed?", options)
        self.assertEqual("yes", result)

    def test_fallback_prompt_with_options_free_text(self) -> None:
        from micro_x_agent_loop.terminal_prompter import fallback_prompt

        options = [
            {"label": "yes", "description": "Go ahead"},
        ]
        with patch("builtins.input", return_value="maybe"):
            with patch("builtins.print"):
                result = fallback_prompt("Proceed?", options)
        self.assertEqual("maybe", result)


if __name__ == "__main__":
    unittest.main()
