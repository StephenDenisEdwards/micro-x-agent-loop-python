"""Tests for Cost Reduction Phases 1 & 2 features."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from micro_x_agent_loop.app_config import AppConfig, parse_app_config
from micro_x_agent_loop.compaction import SummarizeCompactionStrategy
from micro_x_agent_loop.metrics import build_tool_execution_metric
from micro_x_agent_loop.providers.anthropic_provider import AnthropicProvider
from micro_x_agent_loop.provider import create_provider
from micro_x_agent_loop.system_prompt import get_system_prompt, resolve_system_prompt
from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.turn_engine import TurnEngine
from micro_x_agent_loop.turn_events import BaseTurnEvents
from micro_x_agent_loop.usage import UsageResult
from tests.fakes import (
    FakeAnthropicClient,
    FakeProvider,
    FakeStreamContext,
    FakeStreamProvider,
    FakeTool,
)


# ---------------------------------------------------------------------------
# Feature 1: Prompt Caching
# ---------------------------------------------------------------------------


class PromptCachingConfigTests(unittest.TestCase):
    def test_default_enabled(self) -> None:
        config = parse_app_config({})
        self.assertTrue(config.prompt_caching_enabled)

    def test_disabled_via_config(self) -> None:
        config = parse_app_config({"PromptCachingEnabled": False})
        self.assertFalse(config.prompt_caching_enabled)


class PromptCachingProviderTests(unittest.TestCase):
    def _make_provider(self, *, prompt_caching_enabled: bool) -> AnthropicProvider:
        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider._prompt_caching_enabled = prompt_caching_enabled
        return provider

    def test_provider_stores_caching_flag(self) -> None:
        p = self._make_provider(prompt_caching_enabled=True)
        self.assertTrue(p._prompt_caching_enabled)

    def test_stream_chat_adds_cache_control_when_enabled(self) -> None:
        """When caching is enabled, system should be a list with cache_control,
        and the last tool should have cache_control."""
        captured_kwargs: dict[str, Any] = {}

        class CapturingMessages:
            def stream(self, **kwargs):
                captured_kwargs.update(kwargs)
                events: list = []
                final = SimpleNamespace(
                    stop_reason="end_turn",
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                    content=[SimpleNamespace(type="text", text="ok")],
                )
                return FakeStreamContext(events, final)

        class CapturingClient:
            messages = CapturingMessages()

        provider = self._make_provider(prompt_caching_enabled=True)
        provider._client = CapturingClient()

        tools = [
            {"name": "tool_a", "description": "A", "input_schema": {}},
            {"name": "tool_b", "description": "B", "input_schema": {}},
        ]

        asyncio.run(provider.stream_chat(
            "m", 100, 0.5, "system text", [{"role": "user", "content": "hi"}], tools,
        ))

        # System should be a list with cache_control
        system = captured_kwargs["system"]
        self.assertIsInstance(system, list)
        self.assertEqual(1, len(system))
        self.assertEqual("system text", system[0]["text"])
        self.assertEqual({"type": "ephemeral"}, system[0]["cache_control"])

        # Last tool should have cache_control, first should not
        api_tools = captured_kwargs["tools"]
        self.assertNotIn("cache_control", api_tools[0])
        self.assertEqual({"type": "ephemeral"}, api_tools[1]["cache_control"])

    def test_stream_chat_no_cache_control_when_disabled(self) -> None:
        captured_kwargs: dict[str, Any] = {}

        class CapturingMessages:
            def stream(self, **kwargs):
                captured_kwargs.update(kwargs)
                events: list = []
                final = SimpleNamespace(
                    stop_reason="end_turn",
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                    content=[SimpleNamespace(type="text", text="ok")],
                )
                return FakeStreamContext(events, final)

        class CapturingClient:
            messages = CapturingMessages()

        provider = self._make_provider(prompt_caching_enabled=False)
        provider._client = CapturingClient()

        tools = [{"name": "tool_a", "description": "A", "input_schema": {}}]

        asyncio.run(provider.stream_chat(
            "m", 100, 0.5, "system text", [{"role": "user", "content": "hi"}], tools,
        ))

        # System should be plain string
        self.assertEqual("system text", captured_kwargs["system"])
        # Tools should be unchanged
        self.assertNotIn("cache_control", captured_kwargs["tools"][0])

    def test_stream_chat_no_tools_caching_enabled(self) -> None:
        """When caching is enabled but no tools, should not crash."""
        captured_kwargs: dict[str, Any] = {}

        class CapturingMessages:
            def stream(self, **kwargs):
                captured_kwargs.update(kwargs)
                events: list = []
                final = SimpleNamespace(
                    stop_reason="end_turn",
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                    content=[SimpleNamespace(type="text", text="ok")],
                )
                return FakeStreamContext(events, final)

        class CapturingClient:
            messages = CapturingMessages()

        provider = self._make_provider(prompt_caching_enabled=True)
        provider._client = CapturingClient()

        asyncio.run(provider.stream_chat(
            "m", 100, 0.5, "system text", [{"role": "user", "content": "hi"}], [],
        ))

        self.assertIsInstance(captured_kwargs["system"], list)
        self.assertEqual([], captured_kwargs["tools"])


class CreateProviderCachingTests(unittest.TestCase):
    def test_factory_passes_prompt_caching_to_anthropic(self) -> None:
        with patch("micro_x_agent_loop.providers.anthropic_provider.anthropic"):
            provider = create_provider("anthropic", "key", prompt_caching_enabled=True)
            self.assertTrue(provider._prompt_caching_enabled)

    def test_factory_default_no_caching(self) -> None:
        with patch("micro_x_agent_loop.providers.anthropic_provider.anthropic"):
            provider = create_provider("anthropic", "key")
            self.assertFalse(provider._prompt_caching_enabled)


# ---------------------------------------------------------------------------
# Feature 2: Cheaper Compaction Model
# ---------------------------------------------------------------------------


class CompactionModelConfigTests(unittest.TestCase):
    def test_default_empty(self) -> None:
        config = parse_app_config({})
        self.assertEqual("", config.compaction_model)

    def test_custom_model(self) -> None:
        config = parse_app_config({"CompactionModel": "claude-haiku-4-5-20251001"})
        self.assertEqual("claude-haiku-4-5-20251001", config.compaction_model)


class CompactionModelUsageTests(unittest.TestCase):
    def test_compaction_uses_specified_model(self) -> None:
        provider = FakeProvider()
        strategy = SummarizeCompactionStrategy(
            provider, "claude-haiku-4-5-20251001",
            threshold_tokens=1, protected_tail_messages=1,
        )
        messages = [
            {"role": "user", "content": "seed"},
            {"role": "assistant", "content": [{"type": "text", "text": "long " * 200}]},
            {"role": "user", "content": "tail"},
        ]
        asyncio.run(strategy.maybe_compact(messages))
        self.assertEqual(1, len(provider.calls))
        self.assertEqual("claude-haiku-4-5-20251001", provider.calls[0]["model"])


# ---------------------------------------------------------------------------
# Feature 3: Tool Result Summarization
# ---------------------------------------------------------------------------


class ToolSummarizationConfigTests(unittest.TestCase):
    def test_defaults(self) -> None:
        config = parse_app_config({})
        self.assertFalse(config.tool_result_summarization_enabled)
        self.assertEqual("", config.tool_result_summarization_model)
        self.assertEqual(4000, config.tool_result_summarization_threshold)

    def test_enabled(self) -> None:
        config = parse_app_config({
            "ToolResultSummarizationEnabled": True,
            "ToolResultSummarizationModel": "claude-haiku-4-5-20251001",
            "ToolResultSummarizationThreshold": 2000,
        })
        self.assertTrue(config.tool_result_summarization_enabled)
        self.assertEqual("claude-haiku-4-5-20251001", config.tool_result_summarization_model)
        self.assertEqual(2000, config.tool_result_summarization_threshold)


class RecordingEventsForSummarization(BaseTurnEvents):
    def __init__(self) -> None:
        self.appended: list[tuple] = []
        self.api_call_metrics: list[tuple[UsageResult, str]] = []
        self.tool_exec_metrics: list[tuple] = []

    def on_append_message(self, role, content):
        self.appended.append((role, content))
        return f"m{len(self.appended)}"

    def on_api_call_completed(self, usage, call_type):
        self.api_call_metrics.append((usage, call_type))

    def on_tool_executed(self, tool_name, result_chars, duration_ms, is_error, *, was_summarized=False):
        self.tool_exec_metrics.append((tool_name, result_chars, duration_ms, is_error, was_summarized))


class ToolSummarizationEngineTests(unittest.TestCase):
    def _make_engine(
        self,
        provider: FakeStreamProvider,
        events: RecordingEventsForSummarization,
        tools: list[FakeTool],
        *,
        summarization_provider: FakeProvider | None = None,
        summarization_model: str = "",
        summarization_enabled: bool = False,
        summarization_threshold: int = 4000,
    ) -> TurnEngine:
        return TurnEngine(
            provider=provider,
            model="m",
            max_tokens=1024,
            temperature=0.5,
            system_prompt="sys",
            converted_tools=[],
            tool_map={t.name: t for t in tools},
            max_tool_result_chars=100_000,
            max_tokens_retries=3,
            events=events,
            summarization_provider=summarization_provider,
            summarization_model=summarization_model,
            summarization_enabled=summarization_enabled,
            summarization_threshold=summarization_threshold,
        )

    def test_summarization_skipped_when_disabled(self) -> None:
        tool = FakeTool(name="fetch", execute_result="x" * 5000)
        provider = FakeStreamProvider()
        provider.responses.append((
            {"role": "assistant", "content": [{"type": "text", "text": "Fetching."}]},
            [{"name": "fetch", "id": "t1", "input": {}}],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        provider.queue(text="Done.", stop_reason="end_turn")

        events = RecordingEventsForSummarization()
        engine = self._make_engine(provider, events, [tool], summarization_enabled=False)

        asyncio.run(engine.run(messages=[], user_message="go"))

        # Tool result should be full, not summarized
        _, _, _, _, was_summarized = events.tool_exec_metrics[0]
        self.assertFalse(was_summarized)

    def test_summarization_applied_when_enabled_and_above_threshold(self) -> None:
        big_result = "x" * 5000
        tool = FakeTool(name="fetch", execute_result=big_result)
        provider = FakeStreamProvider()
        provider.responses.append((
            {"role": "assistant", "content": [{"type": "text", "text": "Fetching."}]},
            [{"name": "fetch", "id": "t1", "input": {}}],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        provider.queue(text="Done.", stop_reason="end_turn")

        summarization_provider = FakeProvider(summary_text="Short summary of fetch result")
        events = RecordingEventsForSummarization()
        engine = self._make_engine(
            provider, events, [tool],
            summarization_provider=summarization_provider,
            summarization_model="haiku",
            summarization_enabled=True,
            summarization_threshold=1000,
        )

        asyncio.run(engine.run(messages=[], user_message="go"))

        # Tool result should be summarized
        _, result_chars, _, _, was_summarized = events.tool_exec_metrics[0]
        self.assertTrue(was_summarized)
        self.assertLess(result_chars, len(big_result))

        # Summarization API call should be recorded
        summarization_calls = [
            (u, ct) for u, ct in events.api_call_metrics if ct == "tool_summarization"
        ]
        self.assertEqual(1, len(summarization_calls))

    def test_summarization_skipped_when_below_threshold(self) -> None:
        small_result = "short"
        tool = FakeTool(name="fetch", execute_result=small_result)
        provider = FakeStreamProvider()
        provider.responses.append((
            {"role": "assistant", "content": [{"type": "text", "text": "Fetching."}]},
            [{"name": "fetch", "id": "t1", "input": {}}],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        provider.queue(text="Done.", stop_reason="end_turn")

        summarization_provider = FakeProvider(summary_text="should not be called")
        events = RecordingEventsForSummarization()
        engine = self._make_engine(
            provider, events, [tool],
            summarization_provider=summarization_provider,
            summarization_model="haiku",
            summarization_enabled=True,
            summarization_threshold=4000,
        )

        asyncio.run(engine.run(messages=[], user_message="go"))

        _, _, _, _, was_summarized = events.tool_exec_metrics[0]
        self.assertFalse(was_summarized)
        self.assertEqual(0, len(summarization_provider.calls))

    def test_summarization_fallback_on_error(self) -> None:
        """If summarization fails, original result is preserved."""
        big_result = "x" * 5000
        tool = FakeTool(name="fetch", execute_result=big_result)
        provider = FakeStreamProvider()
        provider.responses.append((
            {"role": "assistant", "content": [{"type": "text", "text": "Fetching."}]},
            [{"name": "fetch", "id": "t1", "input": {}}],
            "tool_use",
            UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))
        provider.queue(text="Done.", stop_reason="end_turn")

        class FailingProvider:
            async def create_message(self, *args, **kwargs):
                raise RuntimeError("summarization failed")

        events = RecordingEventsForSummarization()
        engine = self._make_engine(
            provider, events, [tool],
            summarization_provider=FailingProvider(),
            summarization_model="haiku",
            summarization_enabled=True,
            summarization_threshold=1000,
        )

        asyncio.run(engine.run(messages=[], user_message="go"))

        _, result_chars, _, _, was_summarized = events.tool_exec_metrics[0]
        self.assertFalse(was_summarized)
        self.assertEqual(len(big_result), result_chars)


# ---------------------------------------------------------------------------
# Feature 4: Smart Compaction Trigger
# ---------------------------------------------------------------------------


class SmartCompactionConfigTests(unittest.TestCase):
    def test_default_enabled(self) -> None:
        config = parse_app_config({})
        self.assertTrue(config.smart_compaction_trigger_enabled)

    def test_disabled(self) -> None:
        config = parse_app_config({"SmartCompactionTriggerEnabled": False})
        self.assertFalse(config.smart_compaction_trigger_enabled)


class SmartCompactionTriggerTests(unittest.TestCase):
    def test_uses_actual_tokens_when_smart_enabled(self) -> None:
        """When smart trigger is enabled and actual tokens are fed, use them."""
        provider = FakeProvider()
        strategy = SummarizeCompactionStrategy(
            provider, "m",
            threshold_tokens=50_000,
            protected_tail_messages=1,
            smart_trigger_enabled=True,
        )
        messages = [
            {"role": "user", "content": "seed"},
            {"role": "assistant", "content": [{"type": "text", "text": "short"}]},
            {"role": "user", "content": "tail"},
        ]

        # Without feeding actual tokens, tiktoken estimate is small → no compaction
        out = asyncio.run(strategy.maybe_compact(messages))
        self.assertEqual(messages, out)

        # Feed actual tokens above threshold → triggers compaction
        strategy.update_actual_tokens(60_000)
        out = asyncio.run(strategy.maybe_compact(messages))
        self.assertIn("[CONTEXT SUMMARY]", out[0]["content"])

    def test_falls_back_to_estimate_when_smart_disabled(self) -> None:
        provider = FakeProvider()
        strategy = SummarizeCompactionStrategy(
            provider, "m",
            threshold_tokens=50_000,
            protected_tail_messages=1,
            smart_trigger_enabled=False,
        )
        messages = [
            {"role": "user", "content": "seed"},
            {"role": "assistant", "content": [{"type": "text", "text": "short"}]},
            {"role": "user", "content": "tail"},
        ]

        # Even if we update tokens, should use tiktoken estimate
        strategy.update_actual_tokens(60_000)
        out = asyncio.run(strategy.maybe_compact(messages))
        # Tiktoken estimate is small → no compaction
        self.assertEqual(messages, out)

    def test_falls_back_to_estimate_when_no_actual_tokens(self) -> None:
        provider = FakeProvider()
        strategy = SummarizeCompactionStrategy(
            provider, "m",
            threshold_tokens=1,
            protected_tail_messages=1,
            smart_trigger_enabled=True,
        )
        messages = [
            {"role": "user", "content": "seed"},
            {"role": "assistant", "content": [{"type": "text", "text": "long " * 200}]},
            {"role": "user", "content": "tail"},
        ]

        # No actual tokens fed → falls back to tiktoken, which is above threshold=1
        out = asyncio.run(strategy.maybe_compact(messages))
        self.assertIn("[CONTEXT SUMMARY]", out[0]["content"])


# ---------------------------------------------------------------------------
# Feature 5: Concise Output Mode
# ---------------------------------------------------------------------------


class ConciseOutputConfigTests(unittest.TestCase):
    def test_default_disabled(self) -> None:
        config = parse_app_config({})
        self.assertFalse(config.concise_output_enabled)

    def test_enabled(self) -> None:
        config = parse_app_config({"ConciseOutputEnabled": True})
        self.assertTrue(config.concise_output_enabled)


class ConciseOutputSystemPromptTests(unittest.TestCase):
    def test_concise_directive_absent_when_disabled(self) -> None:
        prompt = get_system_prompt(concise_output_enabled=False)
        self.assertNotIn("Minimize output tokens", prompt)

    def test_concise_directive_present_when_enabled(self) -> None:
        prompt = get_system_prompt(concise_output_enabled=True)
        self.assertIn("Minimize output tokens", prompt)
        self.assertIn("200 words", prompt)

    def test_concise_works_with_user_memory(self) -> None:
        prompt = get_system_prompt(
            user_memory="some memory",
            user_memory_enabled=True,
            concise_output_enabled=True,
        )
        self.assertIn("some memory", prompt)
        self.assertIn("Minimize output tokens", prompt)
        self.assertIn("User Memory Guidance", prompt)

    def test_working_directory_absent_by_default(self) -> None:
        prompt = get_system_prompt()
        self.assertNotIn("working directory", prompt.lower())

    def test_working_directory_present_when_set(self) -> None:
        prompt = get_system_prompt(working_directory="/home/user/projects")
        self.assertIn("/home/user/projects", prompt)
        self.assertIn("working directory", prompt.lower())

    def test_working_directory_absent_when_none(self) -> None:
        prompt = get_system_prompt(working_directory=None)
        self.assertNotIn("working directory", prompt.lower())

    def test_platform_info_included(self) -> None:
        import sys
        prompt = get_system_prompt()
        if sys.platform == "win32":
            self.assertIn("Windows", prompt)
            self.assertIn("dir", prompt)
            self.assertNotIn("Unix commands (ls", prompt.lower())
        else:
            self.assertIn("Unix-like", prompt)

    def test_date_is_placeholder_in_template(self) -> None:
        template = get_system_prompt()
        self.assertIn("{current_date}", template)

    def test_resolve_replaces_date_placeholder(self) -> None:
        from datetime import datetime
        template = get_system_prompt()
        resolved = resolve_system_prompt(template)
        self.assertNotIn("{current_date}", resolved)
        today = datetime.now().strftime("%A, %B %d, %Y")
        self.assertIn(today, resolved)


# ---------------------------------------------------------------------------
# Metrics: was_summarized field
# ---------------------------------------------------------------------------


class ToolMetricWasSummarizedTests(unittest.TestCase):
    def test_default_false(self) -> None:
        metric = build_tool_execution_metric(
            tool_name="t", result_chars=100, duration_ms=10.0,
            is_error=False, session_id="s", turn_number=1,
        )
        self.assertFalse(metric["was_summarized"])

    def test_true_when_set(self) -> None:
        metric = build_tool_execution_metric(
            tool_name="t", result_chars=100, duration_ms=10.0,
            is_error=False, session_id="s", turn_number=1,
            was_summarized=True,
        )
        self.assertTrue(metric["was_summarized"])


# ---------------------------------------------------------------------------
# Config parsing: all new fields
# ---------------------------------------------------------------------------


class AllNewConfigFieldsTests(unittest.TestCase):
    def test_all_defaults(self) -> None:
        config = parse_app_config({})
        self.assertTrue(config.prompt_caching_enabled)
        self.assertEqual("", config.compaction_model)
        self.assertFalse(config.tool_result_summarization_enabled)
        self.assertEqual("", config.tool_result_summarization_model)
        self.assertEqual(4000, config.tool_result_summarization_threshold)
        self.assertTrue(config.smart_compaction_trigger_enabled)
        self.assertFalse(config.concise_output_enabled)

    def test_all_custom(self) -> None:
        config = parse_app_config({
            "PromptCachingEnabled": False,
            "CompactionModel": "claude-haiku-4-5-20251001",
            "ToolResultSummarizationEnabled": True,
            "ToolResultSummarizationModel": "claude-haiku-4-5-20251001",
            "ToolResultSummarizationThreshold": 2000,
            "SmartCompactionTriggerEnabled": False,
            "ConciseOutputEnabled": True,
        })
        self.assertFalse(config.prompt_caching_enabled)
        self.assertEqual("claude-haiku-4-5-20251001", config.compaction_model)
        self.assertTrue(config.tool_result_summarization_enabled)
        self.assertEqual("claude-haiku-4-5-20251001", config.tool_result_summarization_model)
        self.assertEqual(2000, config.tool_result_summarization_threshold)
        self.assertFalse(config.smart_compaction_trigger_enabled)
        self.assertTrue(config.concise_output_enabled)


# ---------------------------------------------------------------------------
# Feature 6: CLI Status Bar
# ---------------------------------------------------------------------------


class StatusBarConfigTests(unittest.TestCase):
    def test_default_enabled(self) -> None:
        config = parse_app_config({})
        self.assertTrue(config.status_bar_enabled)

    def test_disabled(self) -> None:
        config = parse_app_config({"StatusBarEnabled": False})
        self.assertFalse(config.status_bar_enabled)


# ---------------------------------------------------------------------------
# Feature 7: Session Budget Caps
# ---------------------------------------------------------------------------


class SessionBudgetConfigTests(unittest.TestCase):
    def test_default_zero(self) -> None:
        config = parse_app_config({})
        self.assertEqual(0.0, config.session_budget_usd)

    def test_custom_budget(self) -> None:
        config = parse_app_config({"SessionBudgetUSD": 1.50})
        self.assertEqual(1.50, config.session_budget_usd)


class SessionBudgetToolbarTests(unittest.TestCase):
    def test_toolbar_no_budget(self) -> None:
        from micro_x_agent_loop.metrics import SessionAccumulator
        acc = SessionAccumulator()
        acc.total_cost_usd = 0.05
        acc.total_turns = 3
        text = acc.format_toolbar()
        self.assertIn("$0.050", text)
        self.assertNotIn("/", text.split("│")[0])  # No budget fraction

    def test_toolbar_with_budget(self) -> None:
        from micro_x_agent_loop.metrics import SessionAccumulator
        acc = SessionAccumulator()
        acc.total_cost_usd = 0.80
        acc.total_turns = 5
        text = acc.format_toolbar(budget_usd=1.00)
        self.assertIn("$0.800/$1.00", text)
        self.assertIn("80%", text)


class SessionBudgetAgentTests(unittest.TestCase):
    """Tests for budget warn/stop logic in Agent."""

    def _make_agent(self, budget: float = 0.0) -> "Agent":
        from micro_x_agent_loop.agent import Agent
        from micro_x_agent_loop.agent_config import AgentConfig
        return Agent(AgentConfig(
            api_key="test",
            session_budget_usd=budget,
            metrics_enabled=True,
        ))

    def test_no_budget_never_exceeded(self) -> None:
        agent = self._make_agent(budget=0.0)
        agent._session_accumulator.total_cost_usd = 999.0
        self.assertFalse(agent._is_budget_exceeded())

    def test_budget_not_exceeded_below(self) -> None:
        agent = self._make_agent(budget=1.0)
        agent._session_accumulator.total_cost_usd = 0.50
        self.assertFalse(agent._is_budget_exceeded())

    def test_budget_exceeded_at_limit(self) -> None:
        agent = self._make_agent(budget=1.0)
        agent._session_accumulator.total_cost_usd = 1.0
        self.assertTrue(agent._is_budget_exceeded())

    def test_budget_exceeded_over_limit(self) -> None:
        agent = self._make_agent(budget=1.0)
        agent._session_accumulator.total_cost_usd = 1.50
        self.assertTrue(agent._is_budget_exceeded())

    def test_warning_emitted_at_threshold(self) -> None:
        agent = self._make_agent(budget=1.0)
        agent._session_accumulator.total_cost_usd = 0.85
        messages: list[str] = []
        agent._system_print = lambda msg: messages.append(msg)
        agent._check_budget_warning()
        self.assertEqual(len(messages), 1)
        self.assertIn("Budget", messages[0])
        self.assertTrue(agent._budget_warning_emitted)

    def test_warning_not_emitted_below_threshold(self) -> None:
        agent = self._make_agent(budget=1.0)
        agent._session_accumulator.total_cost_usd = 0.50
        messages: list[str] = []
        agent._system_print = lambda msg: messages.append(msg)
        agent._check_budget_warning()
        self.assertEqual(len(messages), 0)
        self.assertFalse(agent._budget_warning_emitted)

    def test_warning_emitted_only_once(self) -> None:
        agent = self._make_agent(budget=1.0)
        agent._session_accumulator.total_cost_usd = 0.85
        messages: list[str] = []
        agent._system_print = lambda msg: messages.append(msg)
        agent._check_budget_warning()
        agent._check_budget_warning()  # Second call
        self.assertEqual(len(messages), 1)  # Only one warning

    def test_warning_reset_on_session_reset(self) -> None:
        agent = self._make_agent(budget=1.0)
        agent._budget_warning_emitted = True
        agent._on_session_reset("new-session", [])
        self.assertFalse(agent._budget_warning_emitted)


# ---------------------------------------------------------------------------
# Feature: Per-Turn Model Routing
# ---------------------------------------------------------------------------


class PerTurnRoutingConfigTests(unittest.TestCase):
    def test_default_disabled(self) -> None:
        config = parse_app_config({})
        self.assertFalse(config.per_turn_routing_enabled)

    def test_enabled_via_config(self) -> None:
        config = parse_app_config({
            "PerTurnRoutingEnabled": True,
            "PerTurnRoutingModel": "claude-haiku-4-5-20251001",
            "PerTurnRoutingProvider": "anthropic",
        })
        self.assertTrue(config.per_turn_routing_enabled)
        self.assertEqual(config.per_turn_routing_model, "claude-haiku-4-5-20251001")
        self.assertEqual(config.per_turn_routing_provider, "anthropic")

    def test_custom_thresholds(self) -> None:
        config = parse_app_config({
            "PerTurnRoutingMaxUserChars": 300,
            "PerTurnRoutingShortFollowupChars": 80,
            "PerTurnRoutingComplexityKeywords": "foo,bar,baz",
        })
        self.assertEqual(config.per_turn_routing_max_user_chars, 300)
        self.assertEqual(config.per_turn_routing_short_followup_chars, 80)
        self.assertEqual(config.per_turn_routing_complexity_keywords, "foo,bar,baz")


class PerTurnRoutingTurnEngineTests(unittest.TestCase):
    """Verify TurnEngine routes to cheap model when classifier says so."""

    def test_no_classifier_uses_main_model(self) -> None:
        provider = FakeStreamProvider()
        provider.queue(text="done")
        models_called_2: list[str] = []
        original = provider.stream_chat

        async def tracking(model, *args, **kwargs):
            models_called_2.append(model)
            return await original(model, *args, **kwargs)

        provider.stream_chat = tracking
        events = BaseTurnEvents()
        engine2 = TurnEngine(
            provider=provider, model="main-model", max_tokens=1024, temperature=0.7,
            system_prompt="test", converted_tools=[], tool_map={},
            max_tool_result_chars=40000, max_tokens_retries=1, events=events,
        )
        asyncio.run(engine2.run(messages=[], user_message="hello"))
        self.assertEqual(models_called_2, ["main-model"])

    def test_classifier_routes_to_cheap(self) -> None:
        from micro_x_agent_loop.turn_classifier import TurnClassification

        def always_cheap(**kwargs) -> TurnClassification:
            return TurnClassification(use_cheap_model=True, reason="test", rule="test_rule")

        provider = FakeStreamProvider()
        provider.queue(text="done")
        models_called: list[str] = []
        original = provider.stream_chat

        async def tracking(model, *args, **kwargs):
            models_called.append(model)
            return await original(model, *args, **kwargs)

        provider.stream_chat = tracking
        events = BaseTurnEvents()
        engine = TurnEngine(
            provider=provider, model="main-model", max_tokens=1024, temperature=0.7,
            system_prompt="test", converted_tools=[], tool_map={},
            max_tool_result_chars=40000, max_tokens_retries=1, events=events,
            turn_classifier=always_cheap, routing_model="cheap-model",
        )
        asyncio.run(engine.run(messages=[], user_message="hello"))
        self.assertEqual(models_called, ["cheap-model"])

    def test_classifier_keeps_main(self) -> None:
        from micro_x_agent_loop.turn_classifier import TurnClassification

        def never_cheap(**kwargs) -> TurnClassification:
            return TurnClassification(use_cheap_model=False, reason="test", rule="default")

        provider = FakeStreamProvider()
        provider.queue(text="done")
        models_called: list[str] = []
        original = provider.stream_chat

        async def tracking(model, *args, **kwargs):
            models_called.append(model)
            return await original(model, *args, **kwargs)

        provider.stream_chat = tracking
        events = BaseTurnEvents()
        engine = TurnEngine(
            provider=provider, model="main-model", max_tokens=1024, temperature=0.7,
            system_prompt="test", converted_tools=[], tool_map={},
            max_tool_result_chars=40000, max_tokens_retries=1, events=events,
            turn_classifier=never_cheap, routing_model="cheap-model",
        )
        asyncio.run(engine.run(messages=[], user_message="hello"))
        self.assertEqual(models_called, ["main-model"])

    def test_no_routing_model_stays_main(self) -> None:
        """Even if classifier says cheap, no routing_model means main model."""
        from micro_x_agent_loop.turn_classifier import TurnClassification

        def always_cheap(**kwargs) -> TurnClassification:
            return TurnClassification(use_cheap_model=True, reason="test", rule="test_rule")

        provider = FakeStreamProvider()
        provider.queue(text="done")
        models_called: list[str] = []
        original = provider.stream_chat

        async def tracking(model, *args, **kwargs):
            models_called.append(model)
            return await original(model, *args, **kwargs)

        provider.stream_chat = tracking
        events = BaseTurnEvents()
        engine = TurnEngine(
            provider=provider, model="main-model", max_tokens=1024, temperature=0.7,
            system_prompt="test", converted_tools=[], tool_map={},
            max_tool_result_chars=40000, max_tokens_retries=1, events=events,
            turn_classifier=always_cheap, routing_model="",
        )
        asyncio.run(engine.run(messages=[], user_message="hello"))
        self.assertEqual(models_called, ["main-model"])


class PerTurnRoutingAgentConfigTests(unittest.TestCase):
    """Verify Agent validates per-turn routing config."""

    def test_enabled_without_model_raises(self) -> None:
        from micro_x_agent_loop.agent import Agent
        from micro_x_agent_loop.agent_config import AgentConfig

        with self.assertRaises(ValueError) as ctx:
            Agent(AgentConfig(
                api_key="test",
                per_turn_routing_enabled=True,
                per_turn_routing_model="",
                per_turn_routing_provider="anthropic",
            ))
        self.assertIn("PerTurnRoutingModel", str(ctx.exception))

    def test_enabled_without_provider_raises(self) -> None:
        from micro_x_agent_loop.agent import Agent
        from micro_x_agent_loop.agent_config import AgentConfig

        with self.assertRaises(ValueError) as ctx:
            Agent(AgentConfig(
                api_key="test",
                per_turn_routing_enabled=True,
                per_turn_routing_model="claude-haiku-4-5-20251001",
                per_turn_routing_provider="",
            ))
        self.assertIn("PerTurnRoutingProvider", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
