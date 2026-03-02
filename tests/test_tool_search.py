"""Tests for tool_search — on-demand tool discovery."""

from __future__ import annotations

import asyncio
import unittest

from micro_x_agent_loop.tool_search import (
    TOOL_SEARCH_SCHEMA,
    ToolSearchManager,
    estimate_tool_schema_tokens,
    should_activate_tool_search,
)
from micro_x_agent_loop.turn_engine import TurnEngine
from micro_x_agent_loop.usage import UsageResult
from tests.fakes import FakeStreamProvider, FakeTool
from tests.test_turn_engine import RecordingEvents


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tools() -> list[FakeTool]:
    """Create a set of fake tools for testing search."""
    return [
        FakeTool(name="fs__read_file", description="Read a file from the filesystem"),
        FakeTool(name="fs__write_file", description="Write content to a file"),
        FakeTool(name="fs__list_dir", description="List files in a directory"),
        FakeTool(name="web__search", description="Search the web for information"),
        FakeTool(name="web__fetch", description="Fetch a web page by URL"),
        FakeTool(name="email__send", description="Send an email message"),
        FakeTool(name="email__read", description="Read email messages from inbox"),
        FakeTool(name="code__run_python", description="Execute Python code"),
        FakeTool(name="code__lint", description="Lint source code for errors"),
        FakeTool(name="git__commit", description="Create a git commit"),
    ]


def _convert_tools(tools: list[FakeTool]) -> list[dict]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


# ---------------------------------------------------------------------------
# Activation logic tests
# ---------------------------------------------------------------------------


class TestShouldActivateToolSearch(unittest.TestCase):
    def test_false_always_inactive(self) -> None:
        self.assertFalse(should_activate_tool_search("false", [], "gpt-4o"))

    def test_true_always_active(self) -> None:
        self.assertTrue(should_activate_tool_search("true", [], "gpt-4o"))

    def test_auto_below_threshold(self) -> None:
        # A few small tools shouldn't exceed 40% of 200k context
        tools = _convert_tools(_make_tools())
        self.assertFalse(should_activate_tool_search("auto", tools, "claude-sonnet-4-5"))

    def test_auto_with_custom_threshold(self) -> None:
        # With threshold of 0%, any tools should activate
        tools = _convert_tools(_make_tools())
        self.assertTrue(should_activate_tool_search("auto:0", tools, "claude-sonnet-4-5"))

    def test_unknown_setting_treated_as_false(self) -> None:
        self.assertFalse(should_activate_tool_search("maybe", [], "gpt-4o"))

    def test_auto_colon_invalid_number(self) -> None:
        # "auto:abc" doesn't match the regex, treated as unknown
        self.assertFalse(should_activate_tool_search("auto:abc", [], "gpt-4o"))


# ---------------------------------------------------------------------------
# Token estimation tests
# ---------------------------------------------------------------------------


class TestEstimateToolSchemaTokens(unittest.TestCase):
    def test_empty_list(self) -> None:
        self.assertEqual(0, estimate_tool_schema_tokens([]))

    def test_counts_tokens(self) -> None:
        tools = _convert_tools(_make_tools())
        tokens = estimate_tool_schema_tokens(tools)
        self.assertGreater(tokens, 0)


# ---------------------------------------------------------------------------
# ToolSearchManager tests
# ---------------------------------------------------------------------------


class TestToolSearchManager(unittest.TestCase):
    def _make_manager(self) -> ToolSearchManager:
        tools = _make_tools()
        return ToolSearchManager(all_tools=tools, converted_tools=_convert_tools(tools))

    def test_initial_state(self) -> None:
        mgr = self._make_manager()
        self.assertEqual(0, mgr.loaded_tool_count)
        self.assertEqual(10, mgr.total_tool_count)

    def test_get_tools_for_api_call_initially_only_search(self) -> None:
        mgr = self._make_manager()
        api_tools = mgr.get_tools_for_api_call()
        self.assertEqual(1, len(api_tools))
        self.assertEqual("tool_search", api_tools[0]["name"])

    def test_search_loads_matching_tools(self) -> None:
        mgr = self._make_manager()
        result = mgr.handle_tool_search("file")
        self.assertIn("read_file", result)
        self.assertIn("write_file", result)
        self.assertGreater(mgr.loaded_tool_count, 0)

    def test_loaded_tools_appear_in_api_call(self) -> None:
        mgr = self._make_manager()
        mgr.handle_tool_search("file")
        api_tools = mgr.get_tools_for_api_call()
        names = [t["name"] for t in api_tools]
        self.assertIn("tool_search", names)
        self.assertIn("fs__read_file", names)
        self.assertIn("fs__write_file", names)

    def test_begin_turn_clears_loaded(self) -> None:
        mgr = self._make_manager()
        mgr.handle_tool_search("file")
        self.assertGreater(mgr.loaded_tool_count, 0)
        mgr.begin_turn()
        self.assertEqual(0, mgr.loaded_tool_count)
        api_tools = mgr.get_tools_for_api_call()
        self.assertEqual(1, len(api_tools))

    def test_no_matches_returns_helpful_message(self) -> None:
        mgr = self._make_manager()
        result = mgr.handle_tool_search("zzzznonexistent")
        self.assertIn("No tools found", result)
        self.assertEqual(0, mgr.loaded_tool_count)

    def test_name_match_scores_higher(self) -> None:
        mgr = self._make_manager()
        result = mgr.handle_tool_search("read")
        # "read" appears in both fs__read_file name and email__read name
        self.assertIn("fs__read_file", result)
        self.assertIn("email__read", result)

    def test_is_tool_search_call(self) -> None:
        self.assertTrue(ToolSearchManager.is_tool_search_call("tool_search"))
        self.assertFalse(ToolSearchManager.is_tool_search_call("read_file"))

    def test_multiple_searches_accumulate(self) -> None:
        mgr = self._make_manager()
        mgr.handle_tool_search("file")
        count_after_first = mgr.loaded_tool_count
        mgr.handle_tool_search("email")
        # Should have accumulated more tools
        self.assertGreater(mgr.loaded_tool_count, count_after_first)

    def test_search_schema_structure(self) -> None:
        self.assertEqual("tool_search", TOOL_SEARCH_SCHEMA["name"])
        self.assertIn("query", TOOL_SEARCH_SCHEMA["input_schema"]["properties"])
        self.assertIn("query", TOOL_SEARCH_SCHEMA["input_schema"]["required"])


# ---------------------------------------------------------------------------
# TurnEngine integration tests
# ---------------------------------------------------------------------------


def _make_engine_with_search(
    provider: FakeStreamProvider,
    events: RecordingEvents,
    tools: list[FakeTool] | None = None,
) -> TurnEngine:
    tool_list = tools or _make_tools()
    converted = _convert_tools(tool_list)
    mgr = ToolSearchManager(all_tools=tool_list, converted_tools=converted)
    return TurnEngine(
        provider=provider,
        model="m",
        max_tokens=1024,
        temperature=0.5,
        system_prompt="sys",
        converted_tools=converted,
        tool_map={t.name: t for t in tool_list},
        line_prefix="test> ",
        max_tool_result_chars=40_000,
        max_tokens_retries=3,
        events=events,
        tool_search_manager=mgr,
    )


class TestTurnEngineToolSearch(unittest.TestCase):
    def test_tool_search_then_tool_call(self) -> None:
        """LLM searches for tools, then calls a discovered tool."""
        tool = FakeTool(name="fs__read_file", description="Read a file", execute_result="contents")
        provider = FakeStreamProvider()

        # Response 1: LLM calls tool_search
        provider.responses.append((
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Let me search for file tools."}],
            },
            [{"name": "tool_search", "id": "ts1", "input": {"query": "read file"}}],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        # Response 2: LLM calls the discovered tool
        provider.responses.append((
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Reading the file."}],
            },
            [{"name": "fs__read_file", "id": "t1", "input": {"path": "a.py"}}],
            "tool_use",
            UsageResult(input_tokens=20, output_tokens=10, model="m"),
        ))
        # Response 3: Final text
        provider.queue(text="Here are the contents.", stop_reason="end_turn")

        events = RecordingEvents()
        engine = _make_engine_with_search(provider, events, tools=[tool])

        asyncio.run(engine.run(messages=[], user_message="read a.py"))

        # tool_search should NOT go through execute_tools
        self.assertEqual(1, tool.execute_calls)
        # 3 API calls total
        self.assertEqual(3, len(events.api_call_metrics))

    def test_tool_search_only_continues_loop(self) -> None:
        """When LLM only calls tool_search (no regular tools), loop continues without checkpoint."""
        provider = FakeStreamProvider()

        # Response 1: tool_search only
        provider.responses.append((
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Searching."}],
            },
            [{"name": "tool_search", "id": "ts1", "input": {"query": "email"}}],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        # Response 2: text response
        provider.queue(text="No email tools needed.", stop_reason="end_turn")

        events = RecordingEvents()
        engine = _make_engine_with_search(provider, events)

        asyncio.run(engine.run(messages=[], user_message="check email"))

        # No checkpoint calls (tool_search is handled inline)
        self.assertEqual(0, len(events.checkpoint_calls))
        # 2 API calls
        self.assertEqual(2, len(events.api_call_metrics))

    def test_mixed_search_and_regular_tools(self) -> None:
        """LLM calls tool_search and a regular tool in the same response."""
        tool = FakeTool(name="fs__read_file", description="Read a file", execute_result="data")
        provider = FakeStreamProvider()

        # Response 1: both tool_search and a regular tool
        provider.responses.append((
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Searching and reading."}],
            },
            [
                {"name": "tool_search", "id": "ts1", "input": {"query": "write"}},
                {"name": "fs__read_file", "id": "t1", "input": {"path": "b.py"}},
            ],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        # Response 2: text
        provider.queue(text="Done.", stop_reason="end_turn")

        events = RecordingEvents()
        engine = _make_engine_with_search(provider, events, tools=[tool])

        asyncio.run(engine.run(messages=[], user_message="read and search"))

        self.assertEqual(1, tool.execute_calls)
        # Results should be merged — check that user message has both results
        # The appended messages: user, assistant, user(tool_results), assistant
        tool_result_msg = events.appended[2]
        self.assertEqual("user", tool_result_msg[0])
        results = tool_result_msg[1]
        self.assertEqual(2, len(results))
        # Order should match original: ts1 first, t1 second
        self.assertEqual("ts1", results[0]["tool_use_id"])
        self.assertEqual("t1", results[1]["tool_use_id"])

    def test_no_manager_bypasses_search(self) -> None:
        """Without tool_search_manager, engine works normally."""
        tool = FakeTool(name="read_file", description="Read", execute_result="ok")
        provider = FakeStreamProvider()
        provider.responses.append((
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Reading."}],
            },
            [{"name": "read_file", "id": "t1", "input": {}}],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        provider.queue(text="Done.", stop_reason="end_turn")

        events = RecordingEvents()
        # No tool_search_manager
        engine = TurnEngine(
            provider=provider,
            model="m",
            max_tokens=1024,
            temperature=0.5,
            system_prompt="sys",
            converted_tools=[],
            tool_map={tool.name: tool},
            line_prefix="test> ",
            max_tool_result_chars=40_000,
            max_tokens_retries=3,
            events=events,
        )

        asyncio.run(engine.run(messages=[], user_message="read"))

        self.assertEqual(1, tool.execute_calls)


# ---------------------------------------------------------------------------
# _merge_tool_results tests
# ---------------------------------------------------------------------------


class TestMergeToolResults(unittest.TestCase):
    def test_preserves_original_order(self) -> None:
        original = [
            {"id": "a", "name": "tool_search"},
            {"id": "b", "name": "read_file"},
            {"id": "c", "name": "tool_search"},
        ]
        search_results = [
            {"tool_use_id": "a", "content": "search1"},
            {"tool_use_id": "c", "content": "search2"},
        ]
        regular_results = [
            {"tool_use_id": "b", "content": "file data"},
        ]
        merged = TurnEngine._merge_tool_results(original, search_results, regular_results)
        self.assertEqual(3, len(merged))
        self.assertEqual("a", merged[0]["tool_use_id"])
        self.assertEqual("b", merged[1]["tool_use_id"])
        self.assertEqual("c", merged[2]["tool_use_id"])


if __name__ == "__main__":
    unittest.main()
