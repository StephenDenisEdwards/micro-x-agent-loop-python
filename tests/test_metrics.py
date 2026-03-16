import unittest

from micro_x_agent_loop.metrics import (
    SessionAccumulator,
    _short_model_name,
    build_api_call_metric,
    build_compaction_metric,
    build_session_summary_metric,
    build_tool_execution_metric,
)
from micro_x_agent_loop.usage import UsageResult


class BuildApiCallMetricTests(unittest.TestCase):
    def test_structure(self) -> None:
        usage = UsageResult(
            input_tokens=100,
            output_tokens=50,
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
            duration_ms=1234.5,
        )
        metric = build_api_call_metric(usage, session_id="s1", turn_number=1, call_type="main")
        self.assertEqual("api_call", metric["type"])
        self.assertEqual("s1", metric["session_id"])
        self.assertEqual(1, metric["turn_number"])
        self.assertEqual("main", metric["call_type"])
        self.assertEqual(100, metric["input_tokens"])
        self.assertEqual(50, metric["output_tokens"])
        self.assertEqual("anthropic", metric["provider"])
        self.assertIn("timestamp", metric)
        self.assertIn("estimated_cost_usd", metric)
        self.assertGreater(metric["estimated_cost_usd"], 0)


class BuildToolExecutionMetricTests(unittest.TestCase):
    def test_structure(self) -> None:
        metric = build_tool_execution_metric(
            tool_name="read_file",
            result_chars=400,
            duration_ms=50.0,
            is_error=False,
            session_id="s1",
            turn_number=2,
        )
        self.assertEqual("tool_execution", metric["type"])
        self.assertEqual("read_file", metric["tool_name"])
        self.assertEqual(400, metric["result_chars"])
        self.assertEqual(100, metric["result_estimated_tokens"])
        self.assertFalse(metric["is_error"])


class BuildCompactionMetricTests(unittest.TestCase):
    def test_structure(self) -> None:
        usage = UsageResult(input_tokens=500, output_tokens=200, model="claude-sonnet-4-5-20250929")
        metric = build_compaction_metric(
            usage=usage,
            tokens_before=10000,
            tokens_after=3000,
            messages_compacted=8,
            session_id="s1",
            turn_number=3,
        )
        self.assertEqual("compaction", metric["type"])
        self.assertEqual(10000, metric["estimated_tokens_before"])
        self.assertEqual(3000, metric["estimated_tokens_after"])
        self.assertEqual(7000, metric["tokens_freed"])
        self.assertEqual(8, metric["messages_compacted"])


class SessionAccumulatorTests(unittest.TestCase):
    def test_add_api_call(self) -> None:
        acc = SessionAccumulator(session_id="s1")
        usage = UsageResult(
            input_tokens=100,
            output_tokens=50,
            duration_ms=500.0,
            model="claude-sonnet-4-5-20250929",
        )
        acc.add_api_call(usage)
        self.assertEqual(1, acc.total_api_calls)
        self.assertEqual(100, acc.total_input_tokens)
        self.assertEqual(50, acc.total_output_tokens)
        self.assertEqual(500.0, acc.total_duration_ms)
        self.assertGreater(acc.total_cost_usd, 0)

    def test_add_tool_call(self) -> None:
        acc = SessionAccumulator(session_id="s1")
        acc.add_tool_call("read_file", False)
        acc.add_tool_call("read_file", False)
        acc.add_tool_call("write_file", True)
        self.assertEqual(3, acc.total_tool_calls)
        self.assertEqual(1, acc.total_tool_errors)
        self.assertEqual({"read_file": 2, "write_file": 1}, acc.tool_call_counts)

    def test_add_compaction(self) -> None:
        acc = SessionAccumulator(session_id="s1")
        usage = UsageResult(input_tokens=100, output_tokens=50, model="claude-sonnet-4-5-20250929")
        acc.add_compaction(usage)
        self.assertEqual(1, acc.total_compaction_events)
        self.assertGreater(acc.total_cost_usd, 0)

    def test_format_summary(self) -> None:
        acc = SessionAccumulator(session_id="s1")
        acc.total_turns = 5
        usage = UsageResult(
            input_tokens=1000,
            output_tokens=500,
            duration_ms=2000.0,
            model="claude-sonnet-4-5-20250929",
        )
        acc.add_api_call(usage)
        acc.add_tool_call("bash", False)
        summary = acc.format_summary()
        self.assertIn("Session Cost Summary", summary)
        self.assertIn("1,000", summary)
        self.assertIn("bash: 1", summary)

    def test_build_session_summary_metric(self) -> None:
        acc = SessionAccumulator(session_id="s1")
        acc.total_turns = 3
        acc.add_api_call(UsageResult(input_tokens=100, output_tokens=50, model="claude-sonnet-4-5-20250929"))
        acc.add_tool_call("read_file", False)
        metric = build_session_summary_metric(acc)
        self.assertEqual("session_summary", metric["type"])
        self.assertEqual("s1", metric["session_id"])
        self.assertEqual(3, metric["total_turns"])
        self.assertEqual(1, metric["total_api_calls"])
        self.assertEqual(1, metric["total_tool_calls"])
        self.assertIn("read_file", metric["tool_call_counts"])


    def test_reset_clears_all_counters(self) -> None:
        acc = SessionAccumulator(session_id="s1")
        usage = UsageResult(
            input_tokens=100, output_tokens=50,
            cache_read_input_tokens=20, cache_creation_input_tokens=10,
            duration_ms=500.0, provider="anthropic", model="claude-sonnet-4-5-20250929",
        )
        acc.add_api_call(usage)
        acc.add_tool_call("read_file", False)
        acc.add_compaction(usage)
        acc.total_turns = 5

        acc.reset("s2")

        self.assertEqual("s2", acc.session_id)
        self.assertEqual(0, acc.total_api_calls)
        self.assertEqual(0, acc.total_input_tokens)
        self.assertEqual(0, acc.total_output_tokens)
        self.assertEqual(0, acc.total_cache_read_tokens)
        self.assertEqual(0, acc.total_cache_creation_tokens)
        self.assertEqual(0.0, acc.total_cost_usd)
        self.assertEqual(0, acc.total_tool_calls)
        self.assertEqual(0, acc.total_tool_errors)
        self.assertEqual(0, acc.total_compaction_events)
        self.assertEqual(0, acc.total_turns)
        self.assertEqual(0.0, acc.total_duration_ms)
        self.assertEqual({}, acc.tool_call_counts)
        self.assertEqual({}, acc.model_subtotals)
        self.assertEqual([], acc.api_call_log)

    def test_model_subtotals_tracks_multiple_models(self) -> None:
        acc = SessionAccumulator(session_id="s1")
        usage_main = UsageResult(
            input_tokens=1000, output_tokens=500,
            provider="anthropic", model="claude-sonnet-4-5-20250929",
        )
        usage_cheap = UsageResult(
            input_tokens=200, output_tokens=100,
            provider="anthropic", model="claude-haiku-4-5-20251001",
        )
        acc.add_api_call(usage_main, call_type="main", turn_number=1)
        acc.add_api_call(usage_cheap, call_type="stage2_classification", turn_number=1)
        acc.add_api_call(usage_main, call_type="main", turn_number=2)

        self.assertEqual(2, len(acc.model_subtotals))

        sonnet_key = "anthropic/claude-sonnet-4-5-20250929"
        haiku_key = "anthropic/claude-haiku-4-5-20251001"

        self.assertIn(sonnet_key, acc.model_subtotals)
        self.assertIn(haiku_key, acc.model_subtotals)
        self.assertEqual(2, acc.model_subtotals[sonnet_key]["calls"])
        self.assertEqual(1, acc.model_subtotals[haiku_key]["calls"])
        self.assertEqual(2000, acc.model_subtotals[sonnet_key]["input_tokens"])
        self.assertEqual(200, acc.model_subtotals[haiku_key]["input_tokens"])
        self.assertGreater(
            acc.model_subtotals[sonnet_key]["cost_usd"],
            acc.model_subtotals[haiku_key]["cost_usd"],
        )

    def test_api_call_log_tracks_call_type(self) -> None:
        acc = SessionAccumulator(session_id="s1")
        usage_main = UsageResult(
            input_tokens=1000, output_tokens=500,
            provider="anthropic", model="claude-sonnet-4-5-20250929",
        )
        usage_stage2 = UsageResult(
            input_tokens=300, output_tokens=50,
            provider="anthropic", model="claude-haiku-4-5-20251001",
        )
        acc.add_api_call(usage_main, call_type="main", turn_number=1)
        acc.add_api_call(usage_stage2, call_type="stage2_classification", turn_number=1)

        stage2_entries = [c for c in acc.api_call_log if c["call_type"] == "stage2_classification"]
        self.assertEqual(1, len(stage2_entries))
        self.assertEqual("claude-haiku-4-5-20251001", stage2_entries[0]["model"])


class FormatToolbarTests(unittest.TestCase):
    def test_basic(self) -> None:
        acc = SessionAccumulator(session_id="s1")
        acc.total_turns = 3
        usage = UsageResult(
            input_tokens=2450,
            output_tokens=1200,
            cache_read_input_tokens=1800,
            duration_ms=3000.0,
            model="claude-sonnet-4-20250514",
            provider="anthropic",
        )
        acc.add_api_call(usage)
        toolbar = acc.format_toolbar()
        self.assertIn("T3", toolbar)
        self.assertIn("2,450 in", toolbar)
        self.assertIn("1,200 out", toolbar)
        self.assertIn("cache ", toolbar)
        self.assertIn("sonnet-4", toolbar)
        self.assertIn("$", toolbar)

    def test_no_cache(self) -> None:
        acc = SessionAccumulator(session_id="s1")
        acc.total_turns = 1
        usage = UsageResult(
            input_tokens=100,
            output_tokens=50,
            duration_ms=500.0,
            model="gpt-4.1-mini",
            provider="openai",
        )
        acc.add_api_call(usage)
        toolbar = acc.format_toolbar()
        self.assertNotIn("cache", toolbar)
        self.assertIn("gpt-4.1-mini", toolbar)

    def test_zero_turns(self) -> None:
        acc = SessionAccumulator(session_id="s1")
        toolbar = acc.format_toolbar()
        self.assertIn("$0.000", toolbar)
        self.assertIn("T0", toolbar)
        self.assertIn("0 in", toolbar)
        self.assertIn("0 out", toolbar)
        self.assertNotIn("cache", toolbar)


class ShortModelNameTests(unittest.TestCase):
    def test_anthropic_sonnet(self) -> None:
        self.assertEqual("sonnet-4", _short_model_name("claude-sonnet-4-20250514"))

    def test_anthropic_haiku(self) -> None:
        self.assertEqual("haiku-4-5", _short_model_name("claude-haiku-4-5-20251001"))

    def test_openai_passthrough(self) -> None:
        self.assertEqual("gpt-4.1-mini", _short_model_name("gpt-4.1-mini"))

    def test_anthropic_prefix_no_date(self) -> None:
        self.assertEqual("sonnet-4", _short_model_name("claude-sonnet-4"))


if __name__ == "__main__":
    unittest.main()
