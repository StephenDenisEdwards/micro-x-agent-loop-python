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


class VerbatimToolResultTests(unittest.TestCase):
    """Verifies that file-read tool results survive compaction unchanged.

    Rationale: read_file / grep / glob results are deterministic content the
    model deliberately fetched. Summarising them defeats the purpose, breaks
    the read -> quote -> edit_file workflow, and forces re-reads. Bash and
    other unbounded-output tools still get summarised normally.
    """

    @staticmethod
    def _verbatim_messages() -> list[dict]:
        # Big tool_use+tool_result pair for read_file so it shows up
        # distinctively in the compacted output. The literal sentinel
        # `VERBATIM_FILE_BYTES_KEEP_ME` should survive the compaction.
        return [
            {"role": "user", "content": "seed"},
            {"role": "assistant", "content": [{"type": "text", "text": "padding " * 200}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "tu1", "name": "read_file", "input": {"path": "x.py"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu1", "content": "VERBATIM_FILE_BYTES_KEEP_ME line A\nline B\nline C"},
                ],
            },
            {"role": "assistant", "content": [{"type": "text", "text": "more padding " * 200}]},
            {"role": "user", "content": "tail"},
        ]

    def test_read_file_result_survives_compaction_verbatim(self) -> None:
        strategy = SummarizeCompactionStrategy(FakeProvider(), "m", threshold_tokens=1, protected_tail_messages=1)
        out = asyncio.run(strategy.maybe_compact(self._verbatim_messages()))
        # The verbatim sentinel must appear somewhere in the compacted output.
        flat = "".join(
            block.get("content", "") if isinstance(block.get("content"), str)
            else "".join(
                str(b.get("text") or b.get("content") or "")
                for b in block.get("content", [])
                if isinstance(b, dict)
            )
            for block in out
        )
        self.assertIn("VERBATIM_FILE_BYTES_KEEP_ME", flat)

    def test_playwright_result_survives_compaction_via_wildcard(self) -> None:
        # Playwright tools are exempted via the "playwright__*" wildcard
        # entry in _VERBATIM_TOOL_NAMES, so a browser_snapshot result should
        # be carried through compaction unchanged.
        messages = [
            {"role": "user", "content": "seed"},
            {"role": "assistant", "content": [{"type": "text", "text": "padding " * 200}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "tu1", "name": "playwright__browser_snapshot", "input": {}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu1", "content": "PLAYWRIGHT_DOM_KEEP_ME"},
                ],
            },
            {"role": "assistant", "content": [{"type": "text", "text": "more padding " * 200}]},
            {"role": "user", "content": "tail"},
        ]
        strategy = SummarizeCompactionStrategy(FakeProvider(), "m", threshold_tokens=1, protected_tail_messages=1)
        out = asyncio.run(strategy.maybe_compact(messages))
        flat = "".join(
            block.get("content", "") if isinstance(block.get("content"), str)
            else "".join(
                str(b.get("text") or b.get("content") or "")
                for b in block.get("content", [])
                if isinstance(b, dict)
            )
            for block in out
        )
        self.assertIn("PLAYWRIGHT_DOM_KEEP_ME", flat)

    def test_bash_result_does_not_survive_compaction_verbatim(self) -> None:
        # Same shape but with bash instead of read_file — bash is NOT in
        # _VERBATIM_TOOL_NAMES, so its result should be summarised away.
        messages = [
            {"role": "user", "content": "seed"},
            {"role": "assistant", "content": [{"type": "text", "text": "padding " * 200}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "tu1", "name": "bash", "input": {"command": "ls"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu1", "content": "BASH_OUTPUT_SHOULD_BE_SUMMARISED"},
                ],
            },
            {"role": "assistant", "content": [{"type": "text", "text": "more padding " * 200}]},
            {"role": "user", "content": "tail"},
        ]
        strategy = SummarizeCompactionStrategy(FakeProvider(), "m", threshold_tokens=1, protected_tail_messages=1)
        out = asyncio.run(strategy.maybe_compact(messages))
        flat = "".join(
            block.get("content", "") if isinstance(block.get("content"), str)
            else "".join(
                str(b.get("text") or b.get("content") or "")
                for b in block.get("content", [])
                if isinstance(b, dict)
            )
            for block in out
        )
        # The bash output sentinel should NOT appear verbatim — it gets summarised.
        # (The fake summariser returns its model name, so the sentinel disappears.)
        self.assertNotIn("BASH_OUTPUT_SHOULD_BE_SUMMARISED", flat)

    def test_all_verbatim_compaction_range_skips_summarisation(self) -> None:
        # When every compactable message is verbatim, compaction should
        # bail out and return the original messages unchanged.
        messages = [
            {"role": "user", "content": "seed"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "tu1", "name": "filesystem__read_file", "input": {"path": "a.py"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu1", "content": "x" * 5000},
                ],
            },
            {"role": "user", "content": "tail"},
        ]
        provider = FakeProvider()
        strategy = SummarizeCompactionStrategy(provider, "m", threshold_tokens=1, protected_tail_messages=1)
        out = asyncio.run(strategy.maybe_compact(messages))
        self.assertEqual(messages, out)
        # Provider must not have been called — no summarisation happened.
        self.assertEqual([], provider.calls)


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
