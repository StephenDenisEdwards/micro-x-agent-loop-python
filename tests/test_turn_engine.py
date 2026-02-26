"""Tests for TurnEngine — the core agent loop."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.turn_engine import TurnEngine
from micro_x_agent_loop.turn_events import BaseTurnEvents
from micro_x_agent_loop.usage import UsageResult
from tests.fakes import FakeStreamProvider, FakeTool

# ---------------------------------------------------------------------------
# Recording events helper
# ---------------------------------------------------------------------------


class RecordingEvents(BaseTurnEvents):
    """Records all event calls for assertions."""

    def __init__(self) -> None:
        self.appended: list[tuple[str, Any]] = []
        self.user_message_ids: list[str | None] = []
        self.compact_calls: int = 0
        self.checkpoint_calls: list[list[dict]] = []
        self.mutation_calls: list[tuple[str, Tool, dict]] = []
        self.tool_call_records: list[dict] = []
        self.tool_started: list[tuple[str, str]] = []
        self.tool_completed: list[tuple[str, str, bool]] = []
        self.api_call_metrics: list[tuple[UsageResult, str]] = []
        self.tool_exec_metrics: list[tuple[str, int, float, bool]] = []

    def on_append_message(self, role: str, content: str | list[dict]) -> str | None:
        self.appended.append((role, content))
        return f"m{len(self.appended)}"

    def on_user_message_appended(self, message_id: str | None) -> None:
        self.user_message_ids.append(message_id)

    async def on_maybe_compact(self) -> None:
        self.compact_calls += 1

    def on_ensure_checkpoint_for_turn(self, tool_use_blocks: list[dict]) -> None:
        self.checkpoint_calls.append(tool_use_blocks)

    def on_maybe_track_mutation(self, tool_name: str, tool: Tool, tool_input: dict) -> None:
        self.mutation_calls.append((tool_name, tool, tool_input))

    def on_record_tool_call(self, *, tool_call_id, tool_name, tool_input, result_text, is_error, message_id) -> None:
        self.tool_call_records.append({
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "tool_input": tool_input,
            "result_text": result_text,
            "is_error": is_error,
            "message_id": message_id,
        })

    def on_tool_started(self, tool_use_id: str, tool_name: str) -> None:
        self.tool_started.append((tool_use_id, tool_name))

    def on_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None:
        self.tool_completed.append((tool_use_id, tool_name, is_error))

    def on_api_call_completed(self, usage: UsageResult, call_type: str) -> None:
        self.api_call_metrics.append((usage, call_type))

    def on_tool_executed(self, tool_name: str, result_chars: int, duration_ms: float, is_error: bool) -> None:
        self.tool_exec_metrics.append((tool_name, result_chars, duration_ms, is_error))


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_engine(
    provider: FakeStreamProvider,
    events: RecordingEvents,
    tools: list[FakeTool] | None = None,
    max_tool_result_chars: int = 40_000,
    max_tokens_retries: int = 3,
) -> TurnEngine:
    tool_list = tools or []
    return TurnEngine(
        provider=provider,
        model="m",
        max_tokens=1024,
        temperature=0.5,
        system_prompt="sys",
        converted_tools=[],
        tool_map={t.name: t for t in tool_list},
        line_prefix="test> ",
        max_tool_result_chars=max_tool_result_chars,
        max_tokens_retries=max_tokens_retries,
        events=events,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TurnEngineBasicTests(unittest.TestCase):
    def test_basic_text_response(self) -> None:
        """LLM returns text with no tool calls → immediate return."""
        provider = FakeStreamProvider()
        provider.queue(text="Hello!", stop_reason="end_turn")
        events = RecordingEvents()
        engine = _make_engine(provider, events)

        user_id, assistant_id = asyncio.run(engine.run(messages=[], user_message="hi"))

        self.assertIsNotNone(user_id)
        self.assertIsNotNone(assistant_id)
        # Should have appended user + assistant messages
        self.assertEqual(2, len(events.appended))
        self.assertEqual("user", events.appended[0][0])
        self.assertEqual("assistant", events.appended[1][0])
        # API call metric should fire
        self.assertEqual(1, len(events.api_call_metrics))

    def test_tool_execution_flow(self) -> None:
        """tool_use → execute → tool_result → LLM → text."""
        tool = FakeTool(name="read_file", execute_result="file contents")
        provider = FakeStreamProvider()
        # First response: tool call
        provider.responses.append((
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me read that."},
                    {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "a.py"}},
                ],
            },
            [{"name": "read_file", "id": "t1", "input": {"path": "a.py"}}],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        # Second response: text
        provider.queue(text="Done!", stop_reason="end_turn")

        events = RecordingEvents()
        engine = _make_engine(provider, events, tools=[tool])

        asyncio.run(engine.run(messages=[], user_message="read a.py"))

        self.assertEqual(1, tool.execute_calls)
        # Events: user, assistant(tool_use), user(tool_result), assistant(text)
        self.assertEqual(4, len(events.appended))
        self.assertEqual(1, len(events.tool_started))
        self.assertEqual(1, len(events.tool_completed))
        self.assertEqual(("t1", "read_file"), events.tool_started[0])
        self.assertEqual(("t1", "read_file", False), events.tool_completed[0])

    def test_multiple_tool_calls(self) -> None:
        """Two tools in one response, both executed."""
        tool_a = FakeTool(name="read_file", execute_result="content_a")
        tool_b = FakeTool(name="list_dir", execute_result="content_b")
        provider = FakeStreamProvider()
        provider.responses.append((
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Reading both."}],
            },
            [
                {"name": "read_file", "id": "t1", "input": {"path": "a.py"}},
                {"name": "list_dir", "id": "t2", "input": {"path": "."}},
            ],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        provider.queue(text="All done.", stop_reason="end_turn")

        events = RecordingEvents()
        engine = _make_engine(provider, events, tools=[tool_a, tool_b])

        asyncio.run(engine.run(messages=[], user_message="read both"))

        self.assertEqual(1, tool_a.execute_calls)
        self.assertEqual(1, tool_b.execute_calls)
        self.assertEqual(2, len(events.tool_started))
        self.assertEqual(2, len(events.tool_completed))

    def test_tool_execution_error(self) -> None:
        """Tool raises exception → error result returned to LLM."""
        tool = FakeTool(name="bad_tool", execute_side_effect=RuntimeError("boom"))
        provider = FakeStreamProvider()
        provider.responses.append((
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Trying."}],
            },
            [{"name": "bad_tool", "id": "t1", "input": {}}],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        provider.queue(text="I see the error.", stop_reason="end_turn")

        events = RecordingEvents()
        engine = _make_engine(provider, events, tools=[tool])

        asyncio.run(engine.run(messages=[], user_message="try it"))

        self.assertEqual(1, tool.execute_calls)
        # Tool result should be an error
        error_record = events.tool_call_records[0]
        self.assertTrue(error_record["is_error"])
        self.assertIn("boom", error_record["result_text"])
        # Tool completed with is_error=True
        self.assertEqual(("t1", "bad_tool", True), events.tool_completed[0])

    def test_unknown_tool(self) -> None:
        """LLM calls nonexistent tool → error result."""
        provider = FakeStreamProvider()
        provider.responses.append((
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Calling unknown."}],
            },
            [{"name": "nonexistent", "id": "t1", "input": {}}],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        provider.queue(text="Oh.", stop_reason="end_turn")

        events = RecordingEvents()
        engine = _make_engine(provider, events, tools=[])

        asyncio.run(engine.run(messages=[], user_message="do it"))

        error_record = events.tool_call_records[0]
        self.assertTrue(error_record["is_error"])
        self.assertIn("unknown tool", error_record["result_text"])
        self.assertEqual(("t1", "nonexistent", True), events.tool_completed[0])

    def test_tool_result_truncation(self) -> None:
        """Long result truncated to max_tool_result_chars."""
        long_result = "x" * 200
        tool = FakeTool(name="verbose", execute_result=long_result)
        provider = FakeStreamProvider()
        provider.responses.append((
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Running."}],
            },
            [{"name": "verbose", "id": "t1", "input": {}}],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        provider.queue(text="Got it.", stop_reason="end_turn")

        events = RecordingEvents()
        engine = _make_engine(provider, events, tools=[tool], max_tool_result_chars=50)

        asyncio.run(engine.run(messages=[], user_message="go"))

        result_text = events.tool_call_records[0]["result_text"]
        self.assertIn("OUTPUT TRUNCATED", result_text)
        self.assertLess(len(result_text), len(long_result) + 200)

    def test_max_tokens_retry_then_stop(self) -> None:
        """LLM hits max_tokens N times → stops."""
        provider = FakeStreamProvider()
        for _ in range(3):
            provider.queue(text="cut", stop_reason="max_tokens")

        events = RecordingEvents()
        engine = _make_engine(provider, events, max_tokens_retries=3)

        asyncio.run(engine.run(messages=[], user_message="big request"))

        # Should have 3 API calls
        self.assertEqual(3, len(events.api_call_metrics))
        # After 3 max_tokens, it stops (no further retries)
        self.assertEqual(3, len(provider.stream_calls))

    def test_max_tokens_resets_on_tool_use(self) -> None:
        """max_tokens counter resets when tools are involved."""
        tool = FakeTool(name="read_file", execute_result="ok")
        provider = FakeStreamProvider()
        # max_tokens once
        provider.queue(text="cut1", stop_reason="max_tokens")
        # Then tool_use — should reset counter
        provider.responses.append((
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "reading"}],
            },
            [{"name": "read_file", "id": "t1", "input": {}}],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        # Then text
        provider.queue(text="Done", stop_reason="end_turn")

        events = RecordingEvents()
        engine = _make_engine(provider, events, tools=[tool], max_tokens_retries=3)

        asyncio.run(engine.run(messages=[], user_message="go"))

        # Should have completed successfully (3 API calls, no stop message)
        self.assertEqual(3, len(events.api_call_metrics))
        self.assertEqual(1, tool.execute_calls)

    def test_api_call_metrics_callback(self) -> None:
        """on_api_call_completed called with usage."""
        usage = UsageResult(input_tokens=100, output_tokens=50, model="m")
        provider = FakeStreamProvider()
        provider.responses.append((
            {"role": "assistant", "content": [{"type": "text", "text": "Hi"}]},
            [],
            "end_turn",
            usage,
        ))

        events = RecordingEvents()
        engine = _make_engine(provider, events)

        asyncio.run(engine.run(messages=[], user_message="hello"))

        self.assertEqual(1, len(events.api_call_metrics))
        recorded_usage, call_type = events.api_call_metrics[0]
        self.assertEqual(100, recorded_usage.input_tokens)
        self.assertEqual(50, recorded_usage.output_tokens)
        self.assertEqual("main", call_type)

    def test_tool_executed_metrics_callback(self) -> None:
        """on_tool_executed called with timing."""
        tool = FakeTool(name="read_file", execute_result="result")
        provider = FakeStreamProvider()
        provider.responses.append((
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Reading."}],
            },
            [{"name": "read_file", "id": "t1", "input": {"path": "x"}}],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        provider.queue(text="Done.", stop_reason="end_turn")

        events = RecordingEvents()
        engine = _make_engine(provider, events, tools=[tool])

        asyncio.run(engine.run(messages=[], user_message="read"))

        self.assertEqual(1, len(events.tool_exec_metrics))
        name, chars, duration_ms, is_error = events.tool_exec_metrics[0]
        self.assertEqual("read_file", name)
        self.assertEqual(len("result"), chars)
        self.assertGreaterEqual(duration_ms, 0)
        self.assertFalse(is_error)


if __name__ == "__main__":
    unittest.main()
