import asyncio
import unittest
from unittest.mock import patch

from micro_x_agent_loop.compaction import _adjust_boundary, _rebuild_messages, estimate_tokens
from micro_x_agent_loop.llm_client import Spinner, to_anthropic_tools


class _Tool:
    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "reads files"

    @property
    def input_schema(self) -> dict:
        return {"type": "object"}

    @property
    def is_mutating(self) -> bool:
        return False

    def predict_touched_paths(self, tool_input: dict) -> list[str]:
        return []

    async def execute(self, tool_input: dict) -> str:
        return "ok"


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
        mapped = to_anthropic_tools([_Tool()])
        self.assertEqual("read_file", mapped[0]["name"])
        self.assertEqual("reads files", mapped[0]["description"])

    def test_spinner_start_stop_is_safe(self) -> None:
        spinner = Spinner(prefix="x", label=" test")
        spinner.start()
        asyncio.run(asyncio.sleep(0.01))
        spinner.stop()

if __name__ == "__main__":
    unittest.main()
