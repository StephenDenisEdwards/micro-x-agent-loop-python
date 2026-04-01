"""Extended TurnEngine tests — routing, summarization, subagents, API payload store, nested usage."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from micro_x_agent_loop.api_payload_store import ApiPayloadStore
from micro_x_agent_loop.routing_strategy import RoutingStrategy
from micro_x_agent_loop.semantic_classifier import TaskClassification
from micro_x_agent_loop.task_taxonomy import TaskType
from micro_x_agent_loop.tool import ToolResult
from micro_x_agent_loop.turn_engine import TurnEngine
from micro_x_agent_loop.usage import UsageResult
from tests.fakes import FakeStreamProvider, FakeTool
from tests.test_turn_engine import RecordingEvents


def _make_engine(
    provider: FakeStreamProvider,
    events: RecordingEvents,
    tools: list[FakeTool] | None = None,
    **kwargs: Any,
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
        max_tool_result_chars=40_000,
        max_tokens_retries=3,
        events=events,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Summarization tests
# ---------------------------------------------------------------------------


class SummarizationTests(unittest.TestCase):
    def test_large_result_summarized(self) -> None:
        """Tool result exceeding threshold is summarized."""
        long_result = "x" * 5000
        tool = FakeTool(name="read_file", execute_result=long_result)

        sum_provider = MagicMock()
        sum_provider.create_message = AsyncMock(
            return_value=("short summary", UsageResult(input_tokens=50, output_tokens=10, model="sm"))
        )

        provider = FakeStreamProvider()
        provider.responses.append((
            {"role": "assistant", "content": [{"type": "text", "text": "Reading."}]},
            [{"name": "read_file", "id": "t1", "input": {}}],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        provider.queue(text="Done.", stop_reason="end_turn")

        events = RecordingEvents()
        engine = _make_engine(
            provider, events, tools=[tool],
            summarization_provider=sum_provider,
            summarization_model="sm",
            summarization_enabled=True,
            summarization_threshold=100,
        )

        asyncio.run(engine.run(messages=[], user_message="read"))

        # Summarization should have been called
        sum_provider.create_message.assert_called_once()
        # was_summarized should be True
        self.assertTrue(events.tool_exec_metrics[0][4])  # was_summarized
        # Extra API call for summarization
        self.assertEqual(3, len(events.api_call_metrics))

    def test_small_result_not_summarized(self) -> None:
        tool = FakeTool(name="read_file", execute_result="small")

        sum_provider = MagicMock()
        sum_provider.create_message = AsyncMock()

        provider = FakeStreamProvider()
        provider.responses.append((
            {"role": "assistant", "content": [{"type": "text", "text": "Reading."}]},
            [{"name": "read_file", "id": "t1", "input": {}}],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        provider.queue(text="Done.", stop_reason="end_turn")

        events = RecordingEvents()
        engine = _make_engine(
            provider, events, tools=[tool],
            summarization_provider=sum_provider,
            summarization_model="sm",
            summarization_enabled=True,
            summarization_threshold=1000,
        )

        asyncio.run(engine.run(messages=[], user_message="read"))
        sum_provider.create_message.assert_not_called()

    def test_summarization_failure_returns_original(self) -> None:
        long_result = "x" * 5000
        tool = FakeTool(name="read_file", execute_result=long_result)

        sum_provider = MagicMock()
        sum_provider.create_message = AsyncMock(side_effect=Exception("api error"))

        provider = FakeStreamProvider()
        provider.responses.append((
            {"role": "assistant", "content": [{"type": "text", "text": "Reading."}]},
            [{"name": "read_file", "id": "t1", "input": {}}],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        provider.queue(text="Done.", stop_reason="end_turn")

        events = RecordingEvents()
        engine = _make_engine(
            provider, events, tools=[tool],
            summarization_provider=sum_provider,
            summarization_model="sm",
            summarization_enabled=True,
            summarization_threshold=100,
        )

        asyncio.run(engine.run(messages=[], user_message="read"))
        # Should not crash, was_summarized should be False
        self.assertFalse(events.tool_exec_metrics[0][4])


# ---------------------------------------------------------------------------
# API payload store tests
# ---------------------------------------------------------------------------


class ApiPayloadStoreTests(unittest.TestCase):
    def test_payload_recorded(self) -> None:
        provider = FakeStreamProvider()
        provider.queue(text="Hello!", stop_reason="end_turn")
        events = RecordingEvents()
        store = ApiPayloadStore()
        engine = _make_engine(provider, events, api_payload_store=store)

        asyncio.run(engine.run(messages=[], user_message="hi"))

        self.assertEqual(1, len(store))
        self.assertEqual("m", store.get(0).model)


# ---------------------------------------------------------------------------
# Nested LLM usage tracking
# ---------------------------------------------------------------------------


class NestedLLMUsageTests(unittest.TestCase):
    def test_nested_usage_tracked(self) -> None:
        """Tool returning structured LLM usage gets tracked."""
        tool = FakeTool(name="smart_tool", execute_result="result")
        # Monkey-patch execute to return structured data
        async def patched_execute(tool_input: dict) -> ToolResult:
            tool.execute_calls += 1
            return ToolResult(
                text="result",
                structured={
                    "input_tokens": 500,
                    "output_tokens": 100,
                    "model": "sub-model",
                    "provider": "openai",
                },
            )
        tool.execute = patched_execute  # type: ignore[assignment]

        provider = FakeStreamProvider()
        provider.responses.append((
            {"role": "assistant", "content": [{"type": "text", "text": "Running."}]},
            [{"name": "smart_tool", "id": "t1", "input": {}}],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        provider.queue(text="Done.", stop_reason="end_turn")

        events = RecordingEvents()
        engine = _make_engine(provider, events, tools=[tool])

        asyncio.run(engine.run(messages=[], user_message="go"))

        # Should have 3 API call metrics: main, nested:smart_tool, main
        nested = [m for m in events.api_call_metrics if "nested" in m[1]]
        self.assertEqual(1, len(nested))
        self.assertEqual(500, nested[0][0].input_tokens)


# ---------------------------------------------------------------------------
# Routing target resolution
# ---------------------------------------------------------------------------


class RoutingTargetResolutionTests(unittest.TestCase):
    """Tests for RoutingStrategy._resolve_routing_target (extracted from TurnEngine)."""

    def _make_strategy(self, **kwargs: Any) -> RoutingStrategy:
        defaults: dict[str, Any] = {"default_model": "m"}
        defaults.update(kwargs)
        return RoutingStrategy(**defaults)

    def test_no_classification_returns_none(self) -> None:
        strategy = self._make_strategy(
            routing_policies={"trivial": {"provider": "ollama", "model": "sm"}}
        )
        result = strategy._resolve_routing_target(None)
        self.assertIsNone(result)

    def test_no_policies_returns_none(self) -> None:
        strategy = self._make_strategy()
        classification = TaskClassification(
            task_type=TaskType.TRIVIAL, stage="rules", confidence=0.9, reason="test"
        )
        result = strategy._resolve_routing_target(classification)
        self.assertIsNone(result)

    def test_matching_policy_returns_target(self) -> None:
        strategy = self._make_strategy(
            routing_policies={"trivial": {"provider": "ollama", "model": "sm"}},
            routing_fallback_provider="anthropic",
            routing_fallback_model="m",
        )
        classification = TaskClassification(
            task_type=TaskType.TRIVIAL, stage="rules", confidence=0.9, reason="test"
        )
        result = strategy._resolve_routing_target(classification)
        self.assertIsNotNone(result)
        self.assertEqual("ollama", result.provider)
        self.assertEqual("sm", result.model)

    def test_confidence_gate_refuses_downgrade(self) -> None:
        strategy = self._make_strategy(
            routing_policies={"trivial": {"provider": "ollama", "model": "sm"}},
            routing_fallback_provider="anthropic",
            routing_fallback_model="m",
            routing_confidence_threshold=0.8,
        )
        classification = TaskClassification(
            task_type=TaskType.TRIVIAL, stage="rules", confidence=0.5, reason="uncertain"
        )
        result = strategy._resolve_routing_target(classification)
        self.assertIsNotNone(result)
        self.assertEqual("m", result.model)

    def test_unknown_task_type_falls_back(self) -> None:
        strategy = self._make_strategy(
            routing_policies={"trivial": {"provider": "ollama", "model": "sm"}},
            routing_fallback_provider="anthropic",
            routing_fallback_model="m",
        )
        classification = TaskClassification(
            task_type=TaskType.CODE_GENERATION, stage="rules", confidence=0.9, reason="test"
        )
        result = strategy._resolve_routing_target(classification)
        self.assertIsNotNone(result)
        self.assertEqual("m", result.model)

    def test_policy_with_tool_search_only(self) -> None:
        strategy = self._make_strategy(
            routing_policies={"trivial": {
                "provider": "ollama", "model": "sm",
                "tool_search_only": True,
                "system_prompt": "compact",
                "pin_continuation": True,
            }},
            routing_fallback_provider="anthropic",
            routing_fallback_model="m",
        )
        classification = TaskClassification(
            task_type=TaskType.TRIVIAL, stage="rules", confidence=0.9, reason="test"
        )
        result = strategy._resolve_routing_target(classification)
        self.assertTrue(result.tool_search_only)
        self.assertEqual("compact", result.system_prompt)
        self.assertTrue(result.pin_continuation)

    def test_missing_provider_model_returns_none(self) -> None:
        strategy = self._make_strategy(
            routing_policies={"trivial": {"provider": "", "model": ""}},
        )
        classification = TaskClassification(
            task_type=TaskType.TRIVIAL, stage="rules", confidence=0.9, reason="test"
        )
        result = strategy._resolve_routing_target(classification)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# ask_user pseudo-tool
# ---------------------------------------------------------------------------


class AskUserTests(unittest.TestCase):
    def test_ask_user_handled_inline(self) -> None:
        provider = FakeStreamProvider()
        provider.responses.append((
            {"role": "assistant", "content": [{"type": "text", "text": "Let me ask."}]},
            [{"name": "ask_user", "id": "q1", "input": {"question": "Continue?", "options": ["yes", "no"]}}],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        provider.queue(text="Great.", stop_reason="end_turn")

        events = RecordingEvents()
        channel = MagicMock()
        channel.ask_user = AsyncMock(return_value="yes")

        engine = _make_engine(provider, events, channel=channel)
        asyncio.run(engine.run(messages=[], user_message="do something"))

        channel.ask_user.assert_called_once_with("Continue?", ["yes", "no"])
        # Result should be in appended messages
        inline_msg = events.appended[2]  # user, assistant, user(results)
        self.assertEqual("user", inline_msg[0])


# ---------------------------------------------------------------------------
# max_tokens with channel error emission
# ---------------------------------------------------------------------------


class MaxTokensWithChannelTests(unittest.TestCase):
    def test_error_emitted_to_channel(self) -> None:
        provider = FakeStreamProvider()
        for _ in range(3):
            provider.queue(text="cut", stop_reason="max_tokens")

        events = RecordingEvents()
        channel = MagicMock()

        engine = TurnEngine(
            provider=provider,
            model="m",
            max_tokens=1024,
            temperature=0.5,
            system_prompt="sys",
            converted_tools=[],
            tool_map={},
            max_tool_result_chars=40_000,
            max_tokens_retries=3,
            events=events,
            channel=channel,
        )
        asyncio.run(engine.run(messages=[], user_message="big"))

        channel.emit_error.assert_called_once()
        self.assertIn("max_tokens", channel.emit_error.call_args[0][0])


# ---------------------------------------------------------------------------
# Tool error with is_error in ToolResult
# ---------------------------------------------------------------------------


class ToolResultIsErrorTests(unittest.TestCase):
    def test_tool_result_is_error_raises(self) -> None:
        """When tool.execute returns ToolResult(is_error=True), it's treated as an error."""
        tool = FakeTool(name="err_tool", execute_result="ok")

        async def patched_execute(tool_input: dict) -> ToolResult:
            tool.execute_calls += 1
            return ToolResult(text="something went wrong", is_error=True)
        tool.execute = patched_execute  # type: ignore[assignment]

        provider = FakeStreamProvider()
        provider.responses.append((
            {"role": "assistant", "content": [{"type": "text", "text": "Trying."}]},
            [{"name": "err_tool", "id": "t1", "input": {}}],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        provider.queue(text="I see.", stop_reason="end_turn")

        events = RecordingEvents()
        engine = _make_engine(provider, events, tools=[tool])

        asyncio.run(engine.run(messages=[], user_message="go"))

        error_record = events.tool_call_records[0]
        self.assertTrue(error_record["is_error"])


if __name__ == "__main__":
    unittest.main()
