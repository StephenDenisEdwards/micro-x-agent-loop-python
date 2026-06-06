"""Unit tests for the extracted ToolDispatcher.

These lock the dispatch contract: pseudo vs regular routing, original-order
result merging, and the ``ran_regular_tools`` flag that controls compaction
in TurnEngine.run().
"""

from __future__ import annotations

import unittest

from micro_x_agent_loop.pseudo_tool_handlers import PseudoToolRegistry
from micro_x_agent_loop.tool import Tool, ToolResult
from micro_x_agent_loop.tool_dispatcher import DispatchResult, ToolDispatcher
from micro_x_agent_loop.tool_result_formatter import ToolResultFormatter
from micro_x_agent_loop.turn_events import BaseTurnEvents


class _FakeTool(Tool):
    name = "fake_tool"
    description = "A fake tool"
    input_schema: dict = {"type": "object", "properties": {}}

    def __init__(self, result_text: str = "ok") -> None:
        self._result_text = result_text

    async def execute(self, tool_input: dict) -> ToolResult:
        return ToolResult(text=self._result_text, structured=None, is_error=False)

    @property
    def is_mutating(self) -> bool:
        return False


class _CountingHandler:
    """A pseudo handler that claims the names passed to it and records
    how many blocks it received."""

    def __init__(self, names: set[str]) -> None:
        self._names = frozenset(names)
        self.calls: list[list[dict]] = []

    def claimed_names(self) -> frozenset[str]:
        return self._names

    async def execute_batch(self, blocks: list[dict]) -> list[dict]:
        self.calls.append(list(blocks))
        return [
            {"type": "tool_result", "tool_use_id": b["id"], "content": f"pseudo:{b['name']}"}
            for b in blocks
        ]


def _make_dispatcher(
    *,
    pseudo_handlers: list,
    tool_map: dict[str, Tool] | None = None,
) -> ToolDispatcher:
    return ToolDispatcher(
        pseudo_registry=PseudoToolRegistry(pseudo_handlers),
        tool_map=tool_map or {},
        events=BaseTurnEvents(),
        channel=None,
        formatter=ToolResultFormatter(),
        max_tool_result_chars=0,
        summarization_provider=None,
        summarization_model="",
        summarization_enabled=False,
        summarization_threshold=4000,
        tool_result_overrides={},
    )


class ToolDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_pseudo_only_returns_ran_regular_false(self) -> None:
        handler = _CountingHandler({"ask_user"})
        dispatcher = _make_dispatcher(pseudo_handlers=[handler])

        blocks = [{"id": "a", "name": "ask_user", "input": {}}]
        result = await dispatcher.dispatch(blocks, last_assistant_message_id=None)

        self.assertIsInstance(result, DispatchResult)
        self.assertFalse(result.ran_regular_tools)
        self.assertEqual(["a"], [r["tool_use_id"] for r in result.results])
        self.assertEqual(1, len(handler.calls))

    async def test_regular_only_returns_ran_regular_true(self) -> None:
        tool = _FakeTool("hello")
        dispatcher = _make_dispatcher(pseudo_handlers=[], tool_map={"fake_tool": tool})

        blocks = [{"id": "a", "name": "fake_tool", "input": {}}]
        result = await dispatcher.dispatch(blocks, last_assistant_message_id=None)

        self.assertTrue(result.ran_regular_tools)
        self.assertEqual(1, len(result.results))
        self.assertEqual("hello", result.results[0]["content"])

    async def test_mixed_preserves_original_block_order(self) -> None:
        """When pseudo + regular blocks are interleaved, the merged results
        must come back in the same order as the input blocks. The model
        expects tool_use answers in the same order the calls were made.
        """
        handler = _CountingHandler({"ask_user"})
        tool = _FakeTool("regular-result")
        dispatcher = _make_dispatcher(
            pseudo_handlers=[handler],
            tool_map={"fake_tool": tool},
        )

        blocks = [
            {"id": "b1", "name": "fake_tool", "input": {}},
            {"id": "b2", "name": "ask_user", "input": {}},
            {"id": "b3", "name": "fake_tool", "input": {}},
        ]
        result = await dispatcher.dispatch(blocks, last_assistant_message_id=None)

        self.assertTrue(result.ran_regular_tools)
        self.assertEqual(["b1", "b2", "b3"], [r["tool_use_id"] for r in result.results])
        self.assertEqual("regular-result", result.results[0]["content"])
        self.assertEqual("pseudo:ask_user", result.results[1]["content"])

    async def test_unknown_tool_returns_error_block(self) -> None:
        dispatcher = _make_dispatcher(pseudo_handlers=[], tool_map={})

        blocks = [{"id": "x", "name": "nonexistent", "input": {}}]
        result = await dispatcher.dispatch(blocks, last_assistant_message_id=None)

        self.assertTrue(result.ran_regular_tools)
        self.assertEqual(1, len(result.results))
        self.assertTrue(result.results[0].get("is_error"))
        self.assertIn("unknown tool", result.results[0]["content"])

    async def test_pseudo_handlers_batched_per_handler(self) -> None:
        """A handler claiming multiple names should receive all matching
        blocks in a single execute_batch call (not one call per block)."""
        handler = _CountingHandler({"task_create", "task_update"})
        dispatcher = _make_dispatcher(pseudo_handlers=[handler])

        blocks = [
            {"id": "a", "name": "task_create", "input": {}},
            {"id": "b", "name": "task_update", "input": {}},
        ]
        await dispatcher.dispatch(blocks, last_assistant_message_id=None)

        self.assertEqual(1, len(handler.calls))
        self.assertEqual(["a", "b"], [b["id"] for b in handler.calls[0]])


if __name__ == "__main__":
    unittest.main()
