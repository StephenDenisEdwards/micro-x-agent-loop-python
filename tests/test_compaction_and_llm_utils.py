import asyncio
import unittest

from micro_x_agent_loop.compaction import (
    _adjust_boundary,
    _format_for_summarization,
    _preview_text,
    _rebuild_messages,
    estimate_tokens,
)
from micro_x_agent_loop.llm_client import Spinner
from micro_x_agent_loop.providers.anthropic_provider import AnthropicProvider
from tests.fakes import FakeTool


class CompactionAndLlmUtilsTests(unittest.TestCase):
    def test_estimate_tokens_counts_text_and_tool_blocks(self) -> None:
        messages = [
            {"role": "user", "content": "abcde"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "tool_use", "name": "write_file", "input": {"path": "a.txt"}},
                    {"type": "tool_result", "tool_use_id": "1", "content": "done"},
                ],
            },
        ]
        tokens = estimate_tokens(messages)
        self.assertGreater(tokens, 0)

    def test_adjust_boundary_moves_back_for_tool_use_pair(self) -> None:
        messages = [
            {"role": "user", "content": "start"},
            {"role": "assistant", "content": [{"type": "tool_use", "name": "x", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1", "content": "ok"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "tail"}]},
        ]
        boundary = _adjust_boundary(messages, 0, 2)
        self.assertEqual(1, boundary)

    def test_rebuild_messages_inserts_ack_when_tail_starts_with_user(self) -> None:
        messages = [
            {"role": "user", "content": "original"},
            {"role": "assistant", "content": [{"type": "text", "text": "a"}]},
            {"role": "user", "content": "tail-user"},
        ]
        rebuilt = _rebuild_messages(messages, compact_end=2, summary="summary")
        self.assertEqual("user", rebuilt[0]["role"])
        self.assertEqual("assistant", rebuilt[1]["role"])
        self.assertIn("[CONTEXT SUMMARY]", rebuilt[0]["content"])

    def test_to_anthropic_tools_maps_tool_fields(self) -> None:
        provider = AnthropicProvider.__new__(AnthropicProvider)
        mapped = provider.convert_tools([FakeTool("read_file", "reads files")])
        self.assertEqual("read_file", mapped[0]["name"])
        self.assertEqual("reads files", mapped[0]["description"])

    def test_spinner_start_stop_is_safe(self) -> None:
        spinner = Spinner(prefix="x", label=" test")
        spinner.start()
        asyncio.run(asyncio.sleep(0.01))
        spinner.stop()

class EstimateTokensExtraTests(unittest.TestCase):
    def test_tool_use_block(self) -> None:
        messages = [{
            "role": "assistant",
            "content": [
                {"type": "tool_use", "name": "search", "input": {"q": "hello"}}
            ]
        }]
        tokens = estimate_tokens(messages)
        self.assertGreater(tokens, 0)

    def test_tool_result_with_list_content(self) -> None:
        messages = [{
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "t1",
                "content": [{"type": "text", "text": "result text"}],
            }]
        }]
        tokens = estimate_tokens(messages)
        self.assertGreater(tokens, 0)

    def test_string_block_in_list(self) -> None:
        messages = [{"role": "user", "content": ["hello", "world"]}]
        tokens = estimate_tokens(messages)
        self.assertGreater(tokens, 0)


class FormatForSummarizationTests(unittest.TestCase):
    def test_text_message(self) -> None:
        result = _format_for_summarization([
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ])
        self.assertIn("[user]: hello", result)
        self.assertIn("[assistant]: world", result)

    def test_tool_use_block(self) -> None:
        result = _format_for_summarization([{
            "role": "assistant",
            "content": [{"type": "tool_use", "name": "search", "input": {"q": "foo"}}]
        }])
        self.assertIn("Tool call: search", result)

    def test_tool_use_long_input_truncated(self) -> None:
        result = _format_for_summarization([{
            "role": "assistant",
            "content": [{"type": "tool_use", "name": "x", "input": {"data": "x" * 300}}]
        }])
        self.assertIn("...", result)

    def test_tool_result_string_content(self) -> None:
        result = _format_for_summarization([{
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "result"}]
        }])
        self.assertIn("Tool result", result)

    def test_tool_result_list_content(self) -> None:
        result = _format_for_summarization([{
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "t1",
                "content": [{"type": "text", "text": "partial result"}],
            }]
        }])
        self.assertIn("partial result", result)

    def test_tool_result_other_content(self) -> None:
        result = _format_for_summarization([{
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": 42}]
        }])
        self.assertIn("Tool result", result)


class PreviewTextTests(unittest.TestCase):
    def test_short_text_unchanged(self) -> None:
        text = "short"
        self.assertEqual(text, _preview_text(text))

    def test_long_text_truncated(self) -> None:
        text = "x" * 5000
        result = _preview_text(text)
        self.assertIn("truncated", result)
        self.assertLess(len(result), len(text))


class AdjustBoundaryExtraTests(unittest.TestCase):
    def test_boundary_stops_when_not_assistant(self) -> None:
        messages = [
            {"role": "user", "content": "start"},
            {"role": "user", "content": "another user msg"},
        ]
        # Messages[1] is user (not assistant) - boundary stays at 2
        result = _adjust_boundary(messages, 0, 2)
        self.assertEqual(2, result)

    def test_boundary_stops_for_assistant_without_tool_use(self) -> None:
        messages = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": [{"type": "text", "text": "answer"}]},
        ]
        result = _adjust_boundary(messages, 0, 2)
        self.assertEqual(2, result)

    def test_boundary_non_list_content(self) -> None:
        messages = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "plain string answer"},
        ]
        result = _adjust_boundary(messages, 0, 2)
        self.assertEqual(2, result)


class RebuildMessagesListContentTests(unittest.TestCase):
    def test_first_msg_with_list_content(self) -> None:
        """First message has list content - should extract text blocks."""
        messages = [
            {"role": "user", "content": [
                {"type": "text", "text": "original question"},
                {"type": "text", "text": "more context"},
            ]},
            {"role": "assistant", "content": [{"type": "text", "text": "answer"}]},
            {"role": "user", "content": "tail"},
        ]
        rebuilt = _rebuild_messages(messages, compact_end=2, summary="summary text")
        self.assertIn("original question", rebuilt[0]["content"])
        self.assertIn("[CONTEXT SUMMARY]", rebuilt[0]["content"])


if __name__ == "__main__":
    unittest.main()
