"""Tests for cost_reconciliation module — pure function unit tests."""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime

from micro_x_agent_loop.cost_reconciliation import (
    DIVERGENCE_THRESHOLD_PCT,
    _append_summary,
    _build_daily_report,
    _build_model_report,
    _divergence,
    _flatten_buckets,
    _format_date,
    _get_api_data,
    _parse_cost_report,
    _parse_date,
    _parse_usage_report_to_costs,
    _shorten_model,
)
from micro_x_agent_loop.tool import ToolResult


class ResolveApiKeyIdTests(unittest.TestCase):
    def test_missing_keys_returns_none(self) -> None:
        import os
        from unittest.mock import patch

        from micro_x_agent_loop.cost_reconciliation import _resolve_api_key_id

        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(_resolve_api_key_id())

    def test_missing_admin_key_returns_none(self) -> None:
        import os
        from unittest.mock import patch

        from micro_x_agent_loop.cost_reconciliation import _resolve_api_key_id

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}, clear=True):
            self.assertIsNone(_resolve_api_key_id())

    def test_successful_match(self) -> None:
        import os
        from unittest.mock import MagicMock, patch

        from micro_x_agent_loop.cost_reconciliation import _resolve_api_key_id

        api_key = "sk-ant-api03-HzWxxxxxxQwAA"
        response_data = json.dumps({
            "data": [
                {"id": "apikey_inactive", "partial_key_hint": "sk-ant-api03-Yyy...ZzZz", "status": "inactive"},
                {"id": "apikey_match", "partial_key_hint": "sk-ant-api03-HzW...QwAA", "status": "active"},
            ]
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda s, *a: False

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": api_key, "ANTHROPIC_ADMIN_API_KEY": "admin-key"}):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                result = _resolve_api_key_id()

        self.assertEqual("apikey_match", result)

    def test_no_match_returns_none(self) -> None:
        import os
        from unittest.mock import MagicMock, patch

        from micro_x_agent_loop.cost_reconciliation import _resolve_api_key_id

        response_data = json.dumps({
            "data": [
                {"id": "key1", "partial_key_hint": "sk-ant-api03-Xyz...Other", "status": "active"},
            ]
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda s, *a: False

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-nope", "ANTHROPIC_ADMIN_API_KEY": "admin"}):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                result = _resolve_api_key_id()

        self.assertIsNone(result)

    def test_api_failure_returns_none(self) -> None:
        import os
        from unittest.mock import patch

        from micro_x_agent_loop.cost_reconciliation import _resolve_api_key_id

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test", "ANTHROPIC_ADMIN_API_KEY": "admin"}):
            with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
                result = _resolve_api_key_id()

        self.assertIsNone(result)

    def test_hint_without_dots_skipped(self) -> None:
        import os
        from unittest.mock import MagicMock, patch

        from micro_x_agent_loop.cost_reconciliation import _resolve_api_key_id

        response_data = json.dumps({
            "data": [
                {"id": "key1", "partial_key_hint": "no-dots-here", "status": "active"},
            ]
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda s, *a: False

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test", "ANTHROPIC_ADMIN_API_KEY": "admin"}):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                result = _resolve_api_key_id()

        self.assertIsNone(result)


class FormatDateTests(unittest.TestCase):
    def test_basic(self) -> None:
        dt = datetime(2026, 3, 15, 14, 30, 0, tzinfo=UTC)
        self.assertEqual("2026-03-15T00:00:00Z", _format_date(dt))

    def test_midnight(self) -> None:
        dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        self.assertEqual("2026-01-01T00:00:00Z", _format_date(dt))


class ParseDateTests(unittest.TestCase):
    def test_basic(self) -> None:
        result = _parse_date("2026-03-15")
        self.assertEqual(2026, result.year)
        self.assertEqual(3, result.month)
        self.assertEqual(15, result.day)
        self.assertEqual(UTC, result.tzinfo)

    def test_round_trip(self) -> None:
        dt = _parse_date("2026-01-01")
        self.assertEqual("2026-01-01T00:00:00Z", _format_date(dt))


class ShortenModelTests(unittest.TestCase):
    def test_claude_prefix(self) -> None:
        self.assertEqual("sonnet-4-5-20250929", _shorten_model("claude-sonnet-4-5-20250929"))

    def test_anthropic_claude_prefix(self) -> None:
        self.assertEqual("opus-4-6-20260204", _shorten_model("anthropic/claude-opus-4-6-20260204"))

    def test_no_prefix(self) -> None:
        self.assertEqual("gpt-4o", _shorten_model("gpt-4o"))


class DivergenceTests(unittest.TestCase):
    def test_both_zero(self) -> None:
        diff, status = _divergence(0.0, 0.0)
        self.assertEqual(0.0, diff)
        self.assertEqual("OK", status)

    def test_exact_match(self) -> None:
        diff, status = _divergence(1.0, 1.0)
        self.assertEqual(0.0, diff)
        self.assertEqual("OK", status)

    def test_within_threshold(self) -> None:
        diff, status = _divergence(1.0, 1.04)
        self.assertLess(diff, DIVERGENCE_THRESHOLD_PCT)
        self.assertEqual("OK", status)

    def test_mismatch(self) -> None:
        diff, status = _divergence(1.0, 2.0)
        self.assertGreater(diff, DIVERGENCE_THRESHOLD_PCT)
        self.assertEqual("MISMATCH", status)

    def test_ours_only(self) -> None:
        diff, status = _divergence(1.0, 0.0)
        self.assertEqual(100.0, diff)
        self.assertEqual("MISMATCH", status)


class GetApiDataTests(unittest.TestCase):
    def test_structured_nested_data(self) -> None:
        result = ToolResult(
            text="",
            structured={"data": {"data": [{"starting_at": "2026-03-15", "results": []}]}},
        )
        buckets = _get_api_data(result)
        self.assertEqual(1, len(buckets))

    def test_text_json_with_prefix(self) -> None:
        payload = {"data": [{"starting_at": "2026-03-15", "results": []}]}
        result = ToolResult(text=f"Cost Report:\n{json.dumps(payload)}")
        buckets = _get_api_data(result)
        self.assertEqual(1, len(buckets))

    def test_text_json_no_prefix(self) -> None:
        payload = {"data": [{"starting_at": "2026-03-15", "results": []}]}
        result = ToolResult(text=json.dumps(payload))
        buckets = _get_api_data(result)
        self.assertEqual(1, len(buckets))

    def test_invalid_json_returns_empty(self) -> None:
        result = ToolResult(text="not json")
        self.assertEqual([], _get_api_data(result))

    def test_double_encoded_json(self) -> None:
        inner = json.dumps({"data": [{"starting_at": "2026-03-15", "results": []}]})
        result = ToolResult(text=json.dumps(inner))
        buckets = _get_api_data(result)
        self.assertEqual(1, len(buckets))

    def test_text_list_directly(self) -> None:
        result = ToolResult(text=json.dumps([{"starting_at": "x"}]))
        buckets = _get_api_data(result)
        self.assertEqual(1, len(buckets))


class FlattenBucketsTests(unittest.TestCase):
    def test_basic(self) -> None:
        buckets = [
            {
                "starting_at": "2026-03-15T00:00:00Z",
                "results": [
                    {"model": "claude-sonnet-4-5", "output_tokens": 100},
                    {"model": "claude-haiku-4-5", "output_tokens": 50},
                ],
            }
        ]
        pairs = list(_flatten_buckets(buckets))
        self.assertEqual(2, len(pairs))
        self.assertEqual("2026-03-15", pairs[0][0])

    def test_filter_by_api_key(self) -> None:
        buckets = [
            {
                "starting_at": "2026-03-15T00:00:00Z",
                "results": [
                    {"api_key_id": "key1", "amount": 1.0},
                    {"api_key_id": "key2", "amount": 2.0},
                ],
            }
        ]
        pairs = list(_flatten_buckets(buckets, api_key_id="key1"))
        self.assertEqual(1, len(pairs))
        self.assertEqual(1.0, pairs[0][1]["amount"])

    def test_empty_buckets(self) -> None:
        self.assertEqual([], list(_flatten_buckets([])))

    def test_missing_starting_at(self) -> None:
        self.assertEqual([], list(_flatten_buckets([{"results": [{"x": 1}]}])))

    def test_non_dict_results_skipped(self) -> None:
        buckets = [{"starting_at": "2026-03-15", "results": ["not_a_dict"]}]
        self.assertEqual([], list(_flatten_buckets(buckets)))


class ParseCostReportTests(unittest.TestCase):
    def test_basic(self) -> None:
        payload = {
            "data": [
                {
                    "starting_at": "2026-03-15T00:00:00Z",
                    "results": [
                        {"amount_usd": 0.50},
                        {"amount_usd": 0.25},
                    ],
                }
            ]
        }
        result = ToolResult(text=json.dumps(payload))
        costs = _parse_cost_report(result)
        self.assertAlmostEqual(0.75, costs["2026-03-15"])

    def test_amount_field_fallback(self) -> None:
        payload = {
            "data": [
                {
                    "starting_at": "2026-03-15T00:00:00Z",
                    "results": [{"amount": 1.23}],
                }
            ]
        }
        result = ToolResult(text=json.dumps(payload))
        costs = _parse_cost_report(result)
        self.assertAlmostEqual(1.23, costs["2026-03-15"])


class ParseUsageReportToCostsTests(unittest.TestCase):
    def test_basic(self) -> None:
        payload = {
            "data": [
                {
                    "starting_at": "2026-03-15T00:00:00Z",
                    "results": [
                        {
                            "model": "claude-sonnet-4-5-20250929",
                            "uncached_input_tokens": 1000,
                            "output_tokens": 500,
                            "cache_read_input_tokens": 200,
                            "cache_creation": {"ephemeral_5m_input_tokens": 100},
                        }
                    ],
                }
            ]
        }
        result = ToolResult(text=json.dumps(payload))
        costs = _parse_usage_report_to_costs(result)
        self.assertIn("2026-03-15", costs)
        self.assertIn("claude-sonnet-4-5-20250929", costs["2026-03-15"])
        self.assertGreater(costs["2026-03-15"]["claude-sonnet-4-5-20250929"], 0)

    def test_unknown_model_skipped(self) -> None:
        payload = {
            "data": [
                {
                    "starting_at": "2026-03-15T00:00:00Z",
                    "results": [
                        {"model": "unknown", "uncached_input_tokens": 100, "output_tokens": 50},
                    ],
                }
            ]
        }
        result = ToolResult(text=json.dumps(payload))
        costs = _parse_usage_report_to_costs(result)
        self.assertEqual({}, costs)

    def test_cache_creation_as_int(self) -> None:
        payload = {
            "data": [
                {
                    "starting_at": "2026-03-15T00:00:00Z",
                    "results": [
                        {
                            "model": "claude-sonnet-4-5-20250929",
                            "uncached_input_tokens": 100,
                            "output_tokens": 50,
                            "cache_read_input_tokens": 0,
                            "cache_creation": 200,
                        }
                    ],
                }
            ]
        }
        result = ToolResult(text=json.dumps(payload))
        costs = _parse_usage_report_to_costs(result)
        self.assertGreater(costs["2026-03-15"]["claude-sonnet-4-5-20250929"], 0)


class BuildModelReportTests(unittest.TestCase):
    def test_basic_output(self) -> None:
        local = {"2026-03-15": {"claude-sonnet-4-5-20250929": 0.50}}
        anthropic = {"2026-03-15": {"claude-sonnet-4-5-20250929": 0.52}}
        lines: list[str] = []
        _build_model_report(lines, local, anthropic, 0.50, 0.52)
        text = "\n".join(lines)
        self.assertIn("2026-03-15", text)
        self.assertIn("sonnet-4-5", text)
        self.assertIn("TOTAL", text)
        self.assertIn("OK", text)

    def test_mismatch_shown(self) -> None:
        local = {"2026-03-15": {"claude-sonnet-4-5-20250929": 1.0}}
        anthropic = {"2026-03-15": {"claude-sonnet-4-5-20250929": 0.50}}
        lines: list[str] = []
        _build_model_report(lines, local, anthropic, 1.0, 0.50)
        text = "\n".join(lines)
        self.assertIn("MISMATCH", text)


class BuildDailyReportTests(unittest.TestCase):
    def test_basic_output(self) -> None:
        local = {"2026-03-15": {"model-a": 0.30, "model-b": 0.20}}
        anthropic_daily = {"2026-03-15": 0.52}
        lines: list[str] = []
        _build_daily_report(lines, local, anthropic_daily, 0.50, 0.52)
        text = "\n".join(lines)
        self.assertIn("2026-03-15", text)
        self.assertIn("TOTAL", text)
        self.assertIn("Local per-model breakdown", text)


class AppendSummaryTests(unittest.TestCase):
    def test_ok(self) -> None:
        lines: list[str] = []
        _append_summary(lines, 1.0, 1.02, 0)
        text = "\n".join(lines)
        self.assertIn("OK", text)
        self.assertIn("within threshold", text)

    def test_mismatch_count(self) -> None:
        lines: list[str] = []
        _append_summary(lines, 1.0, 2.0, 3)
        text = "\n".join(lines)
        self.assertIn("MISMATCH", text)
        self.assertIn("3", text)

    def test_anthropic_zero(self) -> None:
        lines: list[str] = []
        _append_summary(lines, 1.0, 0.0, 0)
        text = "\n".join(lines)
        self.assertIn("$0", text)

    def test_both_zero(self) -> None:
        lines: list[str] = []
        _append_summary(lines, 0.0, 0.0, 0)
        text = "\n".join(lines)
        self.assertIn("within threshold", text)


class ReconcileCostsTests(unittest.TestCase):
    """Tests for the reconcile_costs orchestrator with mocked dependencies."""

    def test_missing_tool(self) -> None:
        import asyncio

        from micro_x_agent_loop.cost_reconciliation import reconcile_costs

        lines = asyncio.run(reconcile_costs(tool_map={}, store=None))
        self.assertTrue(any("not available" in line for line in lines))

    def test_missing_store(self) -> None:
        import asyncio
        from unittest.mock import MagicMock

        from micro_x_agent_loop.cost_reconciliation import RECONCILE_TOOL_NAME, reconcile_costs

        fake_tool = MagicMock()
        lines = asyncio.run(reconcile_costs(
            tool_map={RECONCILE_TOOL_NAME: fake_tool}, store=None,
        ))
        self.assertTrue(any("Memory not enabled" in line for line in lines))

    def test_no_local_events(self) -> None:
        import asyncio
        from unittest.mock import MagicMock, patch

        from micro_x_agent_loop.cost_reconciliation import RECONCILE_TOOL_NAME, reconcile_costs

        fake_tool = MagicMock()
        fake_store = MagicMock()
        # _load_local_costs returns empty
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        fake_store.execute.return_value = cursor

        with patch("micro_x_agent_loop.cost_reconciliation._resolve_api_key_id", return_value=None):
            lines = asyncio.run(reconcile_costs(
                tool_map={RECONCILE_TOOL_NAME: fake_tool},
                store=fake_store,
                days=1,
            ))
        self.assertTrue(any("No local metric" in line for line in lines))

    def test_successful_reconciliation_with_usage(self) -> None:
        import asyncio
        from unittest.mock import MagicMock, patch

        from micro_x_agent_loop.cost_reconciliation import RECONCILE_TOOL_NAME, reconcile_costs

        # Use a past date so api_end_dt > start_dt and API calls are made
        past_date = "2026-03-10"
        past_ts = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC).timestamp()

        fake_store = MagicMock()
        event_payload = json.dumps({
            "timestamp": past_ts,
            "model": "claude-sonnet-4-5-20250929",
            "estimated_cost_usd": 0.05,
        })
        cursor = MagicMock()
        cursor.fetchall.return_value = [(event_payload,)]
        fake_store.execute.return_value = cursor

        cost_data = json.dumps({
            "data": [{
                "starting_at": f"{past_date}T00:00:00Z",
                "results": [{"amount_usd": 0.052}],
            }]
        })
        usage_data = json.dumps({
            "data": [{
                "starting_at": f"{past_date}T00:00:00Z",
                "results": [{
                    "model": "claude-sonnet-4-5-20250929",
                    "uncached_input_tokens": 1000,
                    "output_tokens": 500,
                    "cache_read_input_tokens": 200,
                    "cache_creation": {"ephemeral_5m_input_tokens": 100},
                }],
            }]
        })

        call_count = [0]

        async def fake_execute(tool_input: dict) -> ToolResult:
            call_count[0] += 1
            if tool_input.get("action") == "cost":
                return ToolResult(text=cost_data)
            return ToolResult(text=usage_data)

        fake_tool = MagicMock()
        fake_tool.execute = fake_execute

        with patch("micro_x_agent_loop.cost_reconciliation._resolve_api_key_id", return_value="key1"):
            lines = asyncio.run(reconcile_costs(
                tool_map={RECONCILE_TOOL_NAME: fake_tool},
                store=fake_store,
                start=past_date,
                end=past_date,
            ))

        text = "\n".join(lines)
        self.assertIn("Cost Reconciliation", text)
        self.assertIn("key1", text)
        self.assertGreaterEqual(call_count[0], 2)  # cost + usage calls

    def test_with_start_and_end_dates(self) -> None:
        import asyncio
        from unittest.mock import MagicMock, patch

        from micro_x_agent_loop.cost_reconciliation import RECONCILE_TOOL_NAME, reconcile_costs

        fake_store = MagicMock()
        ts = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC).timestamp()
        event_payload = json.dumps({
            "timestamp": ts,
            "model": "claude-sonnet-4-5-20250929",
            "estimated_cost_usd": 0.10,
        })
        cursor = MagicMock()
        cursor.fetchall.return_value = [(event_payload,)]
        fake_store.execute.return_value = cursor

        cost_data = json.dumps({
            "data": [{
                "starting_at": "2026-03-10T00:00:00Z",
                "results": [{"amount_usd": 0.11}],
            }]
        })

        async def fake_execute(tool_input: dict) -> ToolResult:
            return ToolResult(text=cost_data)

        fake_tool = MagicMock()
        fake_tool.execute = fake_execute

        with patch("micro_x_agent_loop.cost_reconciliation._resolve_api_key_id", return_value=None):
            lines = asyncio.run(reconcile_costs(
                tool_map={RECONCILE_TOOL_NAME: fake_tool},
                store=fake_store,
                start="2026-03-10",
                end="2026-03-10",
            ))

        text = "\n".join(lines)
        self.assertIn("2026-03-10", text)

    def test_api_call_error(self) -> None:
        import asyncio
        from unittest.mock import MagicMock, patch

        from micro_x_agent_loop.cost_reconciliation import RECONCILE_TOOL_NAME, reconcile_costs

        fake_store = MagicMock()
        ts = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC).timestamp()
        event_payload = json.dumps({
            "timestamp": ts,
            "model": "claude-sonnet-4-5-20250929",
            "estimated_cost_usd": 0.10,
        })
        cursor = MagicMock()
        cursor.fetchall.return_value = [(event_payload,)]
        fake_store.execute.return_value = cursor

        async def failing_execute(tool_input: dict) -> ToolResult:
            raise RuntimeError("API down")

        fake_tool = MagicMock()
        fake_tool.execute = failing_execute

        with patch("micro_x_agent_loop.cost_reconciliation._resolve_api_key_id", return_value=None):
            lines = asyncio.run(reconcile_costs(
                tool_map={RECONCILE_TOOL_NAME: fake_tool},
                store=fake_store,
                start="2026-03-10",
                end="2026-03-10",
            ))

        text = "\n".join(lines)
        self.assertIn("Error calling", text)

    def test_api_returns_error_result(self) -> None:
        import asyncio
        from unittest.mock import MagicMock, patch

        from micro_x_agent_loop.cost_reconciliation import RECONCILE_TOOL_NAME, reconcile_costs

        fake_store = MagicMock()
        ts = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC).timestamp()
        event_payload = json.dumps({
            "timestamp": ts,
            "model": "claude-sonnet-4-5-20250929",
            "estimated_cost_usd": 0.10,
        })
        cursor = MagicMock()
        cursor.fetchall.return_value = [(event_payload,)]
        fake_store.execute.return_value = cursor

        async def error_execute(tool_input: dict) -> ToolResult:
            return ToolResult(text="forbidden", is_error=True)

        fake_tool = MagicMock()
        fake_tool.execute = error_execute

        with patch("micro_x_agent_loop.cost_reconciliation._resolve_api_key_id", return_value=None):
            lines = asyncio.run(reconcile_costs(
                tool_map={RECONCILE_TOOL_NAME: fake_tool},
                store=fake_store,
                start="2026-03-10",
                end="2026-03-10",
            ))

        text = "\n".join(lines)
        self.assertIn("API error", text)


if __name__ == "__main__":
    unittest.main()
