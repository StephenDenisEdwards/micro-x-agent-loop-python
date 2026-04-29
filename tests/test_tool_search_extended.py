"""Extended tests for tool_search — semantic search, remove_tools, edge cases."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from micro_x_agent_loop.tool_search import (
    ToolSearchManager,
    _get_context_window,
    estimate_tool_schema_tokens,
)
from tests.fakes import FakeTool


def _make_tools() -> list[FakeTool]:
    return [
        FakeTool(name="fs__read_file", description="Read a file from the filesystem"),
        FakeTool(name="fs__write_file", description="Write content to a file"),
        FakeTool(name="web__search", description="Search the web for information"),
        FakeTool(name="email__send", description="Send an email message"),
    ]


def _convert_tools(tools: list[FakeTool]) -> list[dict]:
    return [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools]


class GetContextWindowTests(unittest.TestCase):
    def test_known_model(self) -> None:
        window = _get_context_window("claude-sonnet-4-5")
        self.assertGreater(window, 0)

    def test_unknown_model_returns_default(self) -> None:
        window = _get_context_window("totally-unknown-model-xyz")
        self.assertGreater(window, 0)


class ToolSearchRemoveTests(unittest.TestCase):
    def test_remove_tools(self) -> None:
        tools = _make_tools()
        mgr = ToolSearchManager(all_tools=tools, converted_tools=_convert_tools(tools))
        self.assertEqual(4, mgr.total_tool_count)

        mgr.remove_tools(["fs__read_file", "web__search"])
        self.assertEqual(2, mgr.total_tool_count)
        # Removed tools should not appear in search
        result = asyncio.run(mgr.handle_tool_search("read file"))
        self.assertNotIn("fs__read_file", result)

    def test_remove_empty_list(self) -> None:
        tools = _make_tools()
        mgr = ToolSearchManager(all_tools=tools, converted_tools=_convert_tools(tools))
        mgr.remove_tools([])
        self.assertEqual(4, mgr.total_tool_count)

    def test_remove_nonexistent(self) -> None:
        tools = _make_tools()
        mgr = ToolSearchManager(all_tools=tools, converted_tools=_convert_tools(tools))
        mgr.remove_tools(["nonexistent_tool"])
        self.assertEqual(4, mgr.total_tool_count)

    def test_remove_clears_loaded(self) -> None:
        tools = _make_tools()
        mgr = ToolSearchManager(all_tools=tools, converted_tools=_convert_tools(tools))
        asyncio.run(mgr.handle_tool_search("file"))
        self.assertGreater(mgr.loaded_tool_count, 0)
        mgr.remove_tools(["fs__read_file", "fs__write_file"])
        # loaded_tool_names should have been discarded
        api_tools = mgr.get_tools_for_api_call()
        names = [t["name"] for t in api_tools]
        self.assertNotIn("fs__read_file", names)


class ToolSearchSemanticTests(unittest.TestCase):
    def test_semantic_search_used_when_available(self) -> None:
        tools = _make_tools()
        converted = _convert_tools(tools)

        # Build a fake embedding index
        mock_index = MagicMock()
        mock_index.is_ready = True
        mock_index._client = MagicMock()
        mock_index._client.embed = AsyncMock(return_value=[[0.5, 0.5]])
        mock_index.search = MagicMock(return_value=[("fs__read_file", 0.95)])

        mgr = ToolSearchManager(
            all_tools=tools,
            converted_tools=converted,
            embedding_index=mock_index,
        )

        result = asyncio.run(mgr.handle_tool_search("read a file"))
        self.assertIn("fs__read_file", result)
        self.assertIn("matching tool", result)
        mock_index.search.assert_called_once()

    def test_semantic_search_fallback_to_keyword(self) -> None:
        """When semantic search raises, falls back to keyword search."""
        tools = _make_tools()
        converted = _convert_tools(tools)

        mock_index = MagicMock()
        mock_index.is_ready = True
        mock_index._client = MagicMock()
        mock_index._client.embed = AsyncMock(side_effect=Exception("embed failed"))

        mgr = ToolSearchManager(
            all_tools=tools,
            converted_tools=converted,
            embedding_index=mock_index,
        )

        result = asyncio.run(mgr.handle_tool_search("file"))
        # Should still find tools via keyword
        self.assertIn("fs__read_file", result)

    def test_semantic_search_no_results(self) -> None:
        tools = _make_tools()
        converted = _convert_tools(tools)

        mock_index = MagicMock()
        mock_index.is_ready = True
        mock_index._client = MagicMock()
        mock_index._client.embed = AsyncMock(return_value=[[0.1, 0.1]])
        mock_index.search = MagicMock(return_value=[])

        mgr = ToolSearchManager(
            all_tools=tools,
            converted_tools=converted,
            embedding_index=mock_index,
        )

        result = asyncio.run(mgr.handle_tool_search("zzzznothing"))
        self.assertIn("No tools found", result)

    def test_initialize_embeddings_no_index(self) -> None:
        """initialize_embeddings is a no-op without an index."""
        tools = _make_tools()
        mgr = ToolSearchManager(all_tools=tools, converted_tools=_convert_tools(tools))
        # Should not raise
        asyncio.run(mgr.initialize_embeddings())

    def test_initialize_embeddings_with_index(self) -> None:
        tools = _make_tools()
        converted = _convert_tools(tools)

        mock_index = MagicMock()
        mock_index.build = AsyncMock(return_value=True)

        mgr = ToolSearchManager(
            all_tools=tools,
            converted_tools=converted,
            embedding_index=mock_index,
        )
        asyncio.run(mgr.initialize_embeddings())
        mock_index.build.assert_called_once()


class ToolSearchKeywordMaxLoadTests(unittest.TestCase):
    def test_max_load_limits_results(self) -> None:
        tools = [FakeTool(name=f"tool_{i}", description=f"keyword match tool {i}") for i in range(20)]
        converted = _convert_tools(tools)
        mgr = ToolSearchManager(
            all_tools=tools,
            converted_tools=converted,
            max_load=3,
        )
        result = asyncio.run(mgr.handle_tool_search("keyword"))
        self.assertIn("Showing top 3", result)
        self.assertEqual(3, mgr.loaded_tool_count)

    def test_long_description_truncated_in_output(self) -> None:
        tools = [FakeTool(name="fs__tool", description="x" * 300)]
        converted = _convert_tools(tools)
        mgr = ToolSearchManager(all_tools=tools, converted_tools=converted)
        result = asyncio.run(mgr.handle_tool_search("tool"))
        self.assertIn("...", result)


class EstimateTokensTests(unittest.TestCase):
    def test_schemas_with_complex_input(self) -> None:
        tools = [
            {
                "name": "complex_tool",
                "description": "A complex tool with nested schema",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "nested": {"type": "object", "properties": {"a": {"type": "string"}}},
                    },
                },
            }
        ]
        tokens = estimate_tool_schema_tokens(tools)
        self.assertGreater(tokens, 0)


if __name__ == "__main__":
    unittest.main()
