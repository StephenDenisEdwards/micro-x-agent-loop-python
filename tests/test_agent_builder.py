"""Direct tests for ``build_agent_components`` — verifies wiring & branch points.

Mocks ``create_provider`` so the builder doesn't hit any network or
require API keys. Asserts that switches in the input config produce the
right collaborator presence/absence in ``AgentComponents``.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from micro_x_agent_loop.agent_config import AgentConfig
from micro_x_agent_loop.compaction import NoneCompactionStrategy
from tests.fakes import FakeTool


def _fake_provider() -> MagicMock:
    """A provider stand-in that satisfies the calls build_agent_components makes."""
    prov = MagicMock()
    prov.convert_tools.return_value = []
    return prov


class BuildAgentComponentsTests(unittest.TestCase):
    def _minimal_config(self, **overrides) -> AgentConfig:
        defaults: dict = {
            "model": "test-model",
            "max_tokens": 1024,
            "temperature": 0.5,
            "api_key": "test-key",
            "provider": "anthropic",
            "tools": [],
            "system_prompt": "test prompt",
            "compaction_strategy": NoneCompactionStrategy(),
            "memory_enabled": False,
            "metrics_enabled": True,
            "session_budget_usd": 0.0,
            "markdown_rendering_enabled": True,
        }
        defaults.update(overrides)
        return AgentConfig(**defaults)

    def _build(self, config: AgentConfig):
        from micro_x_agent_loop.agent_builder import build_agent_components

        with patch(
            "micro_x_agent_loop.agent_builder.create_provider",
            return_value=_fake_provider(),
        ):
            return build_agent_components(config)

    def test_minimal_config_returns_components_with_no_optional_subsystems(self) -> None:
        c = self._build(self._minimal_config())
        self.assertIsNone(c.tool_search_manager)
        self.assertIsNone(c.sub_agent_runner)
        self.assertIsNone(c.task_manager)
        self.assertIsNone(c.summarization_provider)
        self.assertIsNone(c.stage2_provider)
        self.assertIsNone(c.provider_pool)
        self.assertIsNone(c.semantic_classifier)
        self.assertIsNone(c.routing_feedback_store)
        self.assertIsNone(c.task_embedding_index)
        self.assertFalse(c.tool_search_active)
        self.assertFalse(c.semantic_routing_enabled)

    def test_autonomous_uses_empty_line_prefix(self) -> None:
        c = self._build(self._minimal_config(autonomous=True))
        self.assertEqual("", c.line_prefix)
        self.assertTrue(c.autonomous)

    def test_interactive_uses_assistant_prefix(self) -> None:
        c = self._build(self._minimal_config(autonomous=False))
        self.assertEqual("assistant> ", c.line_prefix)
        self.assertFalse(c.autonomous)

    def test_summarization_enabled_creates_provider(self) -> None:
        c = self._build(
            self._minimal_config(
                tool_result_summarization_enabled=True,
                tool_result_summarization_model="summary-model",
            )
        )
        self.assertIsNotNone(c.summarization_provider)
        self.assertEqual("summary-model", c.summarization_model)
        self.assertTrue(c.summarization_enabled)

    def test_summarization_defaults_model_to_main_model(self) -> None:
        c = self._build(
            self._minimal_config(
                tool_result_summarization_enabled=True,
                tool_result_summarization_model="",
                model="main-model",
            )
        )
        self.assertEqual("main-model", c.summarization_model)

    def test_sub_agents_enabled_requires_provider(self) -> None:
        # SubAgentsEnabled with no SubAgentProvider should raise
        config = self._minimal_config(
            sub_agents_enabled=True,
            sub_agent_provider="",
            sub_agent_model="some-model",
        )
        with self.assertRaises(ValueError) as cm:
            self._build(config)
        self.assertIn("SubAgentProvider", str(cm.exception))

    def test_sub_agents_enabled_requires_model(self) -> None:
        config = self._minimal_config(
            sub_agents_enabled=True,
            sub_agent_provider="anthropic",
            sub_agent_model="",
        )
        with self.assertRaises(ValueError) as cm:
            self._build(config)
        self.assertIn("SubAgentModel", str(cm.exception))

    def test_stage2_enabled_requires_provider(self) -> None:
        # When Stage2Provider is missing, the builder rejects the config.
        # Note: build_agent_components currently creates the provider before
        # validating that the name is set, so the resolve_runtime_env call
        # surfaces the missing env var first when stage2_provider is empty.
        config = self._minimal_config(
            stage2_classification_enabled=True,
            stage2_provider="",
            stage2_model="some-model",
        )
        with self.assertRaises((ValueError, RuntimeError)):
            self._build(config)

    def test_memory_enabled_without_session_manager_falls_back_to_null(self) -> None:
        # MemoryEnabled=True but no session_manager wired → NullMemoryFacade
        c = self._build(
            self._minimal_config(
                memory_enabled=True,
                session_manager=None,
                session_id="sess-123",
            )
        )
        # The facade should be a Null one, and the active session id is set on it.
        from micro_x_agent_loop.memory.facade import NullMemoryFacade

        self.assertIsInstance(c.memory, NullMemoryFacade)
        self.assertEqual("sess-123", c.memory.active_session_id)

    def test_tools_are_indexed_into_tool_map(self) -> None:
        t1 = FakeTool("server__one")
        t2 = FakeTool("server__two")
        c = self._build(self._minimal_config(tools=[t1, t2]))
        self.assertIn("server__one", c.tool_map)
        self.assertIn("server__two", c.tool_map)

    def test_routing_fallback_defaults_to_main_provider_and_model(self) -> None:
        # When fallback is unset, builder falls back to the main provider/model.
        c = self._build(
            self._minimal_config(
                provider="anthropic",
                model="main-model",
                routing_fallback_provider="",
                routing_fallback_model="",
            )
        )
        self.assertEqual("anthropic", c.routing_fallback_provider)
        self.assertEqual("main-model", c.routing_fallback_model)

    def test_explicit_routing_fallback_preserved(self) -> None:
        c = self._build(
            self._minimal_config(
                provider="anthropic",
                model="main-model",
                routing_fallback_provider="openai",
                routing_fallback_model="fallback-model",
            )
        )
        self.assertEqual("openai", c.routing_fallback_provider)
        self.assertEqual("fallback-model", c.routing_fallback_model)


if __name__ == "__main__":
    unittest.main()
