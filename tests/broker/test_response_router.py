"""Tests for ResponseRouter."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from micro_x_agent_loop.broker.response_router import ResponseRouter
from micro_x_agent_loop.broker.runner import RunResult


def _make_store() -> MagicMock:
    store = MagicMock()
    store.mark_response_sent = MagicMock()
    store.mark_response_failed = MagicMock()
    return store


def _make_adapter(*, send_result: bool = True) -> MagicMock:
    adapter = MagicMock()
    adapter.send_response = AsyncMock(return_value=send_result)
    return adapter


class ResponseRouterTests(unittest.TestCase):
    def test_channel_none_returns_true(self) -> None:
        router = ResponseRouter({})
        store = _make_store()
        result_obj = RunResult(exit_code=0, stdout="", stderr="")
        result = asyncio.run(router.route("run1", "none", None, result_obj, store))
        self.assertTrue(result)
        store.mark_response_sent.assert_not_called()

    def test_known_channel_success(self) -> None:
        adapter = _make_adapter(send_result=True)
        log_adapter = _make_adapter(send_result=True)
        router = ResponseRouter({"http": adapter, "log": log_adapter})
        store = _make_store()
        result_obj = RunResult(exit_code=0, stdout="done", stderr="")
        sent = asyncio.run(router.route("run-abc123", "http", "http://target", result_obj, store))
        self.assertTrue(sent)
        store.mark_response_sent.assert_called_once_with("run-abc123")
        store.mark_response_failed.assert_not_called()

    def test_known_channel_failure_falls_back_to_log(self) -> None:
        adapter = _make_adapter(send_result=False)
        log_adapter = _make_adapter(send_result=True)
        router = ResponseRouter({"http": adapter, "log": log_adapter})
        store = _make_store()
        result_obj = RunResult(exit_code=1, stdout="", stderr="fail")
        sent = asyncio.run(router.route("run-abc123", "http", None, result_obj, store))
        self.assertFalse(sent)
        store.mark_response_failed.assert_called_once()
        log_adapter.send_response.assert_called_once()

    def test_unknown_channel_falls_back_to_log(self) -> None:
        log_adapter = _make_adapter(send_result=True)
        router = ResponseRouter({"log": log_adapter})
        store = _make_store()
        result_obj = RunResult(exit_code=0, stdout="ok", stderr="")
        sent = asyncio.run(router.route("run1", "unknown_channel", None, result_obj, store))
        self.assertTrue(sent)
        log_adapter.send_response.assert_called_once()

    def test_unknown_channel_no_log_returns_false(self) -> None:
        router = ResponseRouter({})
        store = _make_store()
        result_obj = RunResult(exit_code=0, stdout="", stderr="")
        sent = asyncio.run(router.route("run1", "missing", None, result_obj, store))
        self.assertFalse(sent)

    def test_adapter_exception_marks_failed(self) -> None:
        adapter = MagicMock()
        adapter.send_response = AsyncMock(side_effect=Exception("network error"))
        log_adapter = _make_adapter(send_result=True)
        router = ResponseRouter({"http": adapter, "log": log_adapter})
        store = _make_store()
        result_obj = RunResult(exit_code=0, stdout="", stderr="")
        sent = asyncio.run(router.route("run1", "http", "target", result_obj, store))
        self.assertFalse(sent)
        store.mark_response_failed.assert_called_once()

    def test_log_channel_success_no_fallback(self) -> None:
        log_adapter = _make_adapter(send_result=False)
        router = ResponseRouter({"log": log_adapter})
        store = _make_store()
        result_obj = RunResult(exit_code=0, stdout="", stderr="")
        sent = asyncio.run(router.route("run1", "log", None, result_obj, store))
        self.assertFalse(sent)
        # Should not call log again (already on log channel)
        self.assertEqual(1, log_adapter.send_response.call_count)


if __name__ == "__main__":
    unittest.main()
