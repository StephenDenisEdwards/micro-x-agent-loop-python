import asyncio
import unittest
from unittest.mock import patch

from micro_x_agent_loop.compaction import NoneCompactionStrategy, SummarizeCompactionStrategy, _format_for_summarization
from micro_x_agent_loop.usage import UsageResult
from tests.fakes import FakeProvider


class CompactionStrategyTests(unittest.TestCase):
    def test_format_for_summarization_includes_tool_blocks(self) -> None:
        messages = [
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "ok"},
                    {"type": "tool_use", "name": "read_file", "input": {"path": "x"}},
                    {"type": "tool_result", "tool_use_id": "1", "content": "done"},
                ],
            },
        ]
        formatted = _format_for_summarization(messages)
        self.assertIn("[user]: hello", formatted)
        self.assertIn("[Tool call: read_file", formatted)
        self.assertIn("[Tool result (1)]:", formatted)

    def test_maybe_compact_returns_original_below_threshold(self) -> None:
        strategy = SummarizeCompactionStrategy(FakeProvider(), "m", threshold_tokens=10_000)
        messages = [{"role": "user", "content": "small"}]
        out = asyncio.run(strategy.maybe_compact(messages))
        self.assertEqual(messages, out)

    def test_maybe_compact_summarizes_when_over_threshold(self) -> None:
        strategy = SummarizeCompactionStrategy(FakeProvider(), "m", threshold_tokens=1, protected_tail_messages=1)
        messages = [
            {"role": "user", "content": "seed"},
            {"role": "assistant", "content": [{"type": "text", "text": "long text " * 200}]},
            {"role": "user", "content": "tail"},
        ]
        out = asyncio.run(strategy.maybe_compact(messages))
        self.assertGreaterEqual(len(out), 2)
        self.assertIn("[CONTEXT SUMMARY]", out[0]["content"])

    def test_maybe_compact_falls_back_on_summary_error(self) -> None:
        strategy = SummarizeCompactionStrategy(FakeProvider(), "m", threshold_tokens=1, protected_tail_messages=1)
        messages = [
            {"role": "user", "content": "seed"},
            {"role": "assistant", "content": [{"type": "text", "text": "long text " * 200}]},
            {"role": "user", "content": "tail"},
        ]
        with patch("micro_x_agent_loop.compaction._summarize", side_effect=RuntimeError("boom")):
            out = asyncio.run(strategy.maybe_compact(messages))
        self.assertEqual(messages, out)

    def test_summarize_calls_provider_create_message(self) -> None:
        provider = FakeProvider()
        strategy = SummarizeCompactionStrategy(provider, "m", threshold_tokens=1, protected_tail_messages=1)
        messages = [
            {"role": "user", "content": "seed"},
            {"role": "assistant", "content": [{"type": "text", "text": "long text " * 200}]},
            {"role": "user", "content": "tail"},
        ]
        asyncio.run(strategy.maybe_compact(messages))
        self.assertGreaterEqual(len(provider.calls), 1)

    def test_compaction_callback_invoked(self) -> None:
        callback_calls: list[tuple] = []

        def on_compaction(usage, tokens_before, tokens_after, messages_compacted):
            callback_calls.append((usage, tokens_before, tokens_after, messages_compacted))

        provider = FakeProvider()
        strategy = SummarizeCompactionStrategy(
            provider,
            "m",
            threshold_tokens=1,
            protected_tail_messages=1,
            on_compaction_completed=on_compaction,
        )
        messages = [
            {"role": "user", "content": "seed"},
            {"role": "assistant", "content": [{"type": "text", "text": "long text " * 200}]},
            {"role": "user", "content": "tail"},
        ]
        asyncio.run(strategy.maybe_compact(messages))
        self.assertEqual(1, len(callback_calls))
        usage, tokens_before, tokens_after, messages_compacted = callback_calls[0]
        self.assertIsInstance(usage, UsageResult)
        self.assertGreater(tokens_before, 0)
        self.assertEqual(1, messages_compacted)


class NoneCompactionStrategyTests(unittest.TestCase):
    def test_returns_messages_unchanged(self) -> None:
        strategy = NoneCompactionStrategy()
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        out = asyncio.run(strategy.maybe_compact(messages))
        self.assertIs(out, messages)

    def test_returns_empty_list_unchanged(self) -> None:
        strategy = NoneCompactionStrategy()
        messages: list[dict] = []
        out = asyncio.run(strategy.maybe_compact(messages))
        self.assertIs(out, messages)


if __name__ == "__main__":
    unittest.main()
