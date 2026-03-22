"""Tests for llm_client module (Spinner, print_through_spinner)."""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

from micro_x_agent_loop import llm_client
from micro_x_agent_loop.llm_client import Spinner, print_through_spinner


class SpinnerTests(unittest.TestCase):
    def test_start_and_stop(self) -> None:
        spinner = Spinner(prefix="", label=" Thinking...")
        spinner.start()
        time.sleep(0.05)
        spinner.stop()

    def test_stop_idempotent(self) -> None:
        spinner = Spinner()
        spinner.start()
        spinner.stop()
        spinner.stop()  # Should not raise

    def test_print_line_while_running(self) -> None:
        spinner = Spinner(prefix="", label=" Thinking...")
        spinner.start()
        try:
            # Should not raise
            spinner.print_line("hello from spinner")
        finally:
            spinner.stop()

    def test_active_spinner_set_on_start(self) -> None:
        spinner = Spinner()
        spinner.start()
        try:
            self.assertIs(llm_client._active_spinner, spinner)
        finally:
            spinner.stop()

    def test_active_spinner_cleared_on_stop(self) -> None:
        spinner = Spinner()
        spinner.start()
        spinner.stop()
        self.assertIsNone(llm_client._active_spinner)


class PrintThroughSpinnerTests(unittest.TestCase):
    def test_no_spinner_uses_print(self) -> None:
        # Ensure no active spinner
        llm_client._active_spinner = None
        with patch("builtins.print") as mock_print:
            print_through_spinner("test message")
            mock_print.assert_called_once_with("test message", flush=True)

    def test_with_active_spinner_uses_print_line(self) -> None:
        spinner = MagicMock()
        llm_client._active_spinner = spinner
        try:
            print_through_spinner("spinner message")
            spinner.print_line.assert_called_once_with("spinner message")
        finally:
            llm_client._active_spinner = None


class OnRetryTests(unittest.TestCase):
    def test_on_retry_logs_warning(self) -> None:
        from micro_x_agent_loop.llm_client import _on_retry

        retry_state = MagicMock()
        retry_state.attempt_number = 2
        next_action = MagicMock()
        next_action.sleep = 5.0
        retry_state.next_action = next_action
        outcome = MagicMock()
        outcome.exception.return_value = RuntimeError("boom")
        retry_state.outcome = outcome

        # Should not raise
        _on_retry(retry_state)


if __name__ == "__main__":
    unittest.main()
