"""Tests for provider_pool module."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from micro_x_agent_loop.provider_pool import ProviderPool, ProviderStatus, RoutingTarget


def _make_fake_provider(name: str = "fake", family: str = "openai") -> MagicMock:
    """Create a fake provider with async methods."""
    provider = MagicMock()
    provider.family = family
    provider.stream_chat = AsyncMock(return_value=(
        {"content": [{"type": "text", "text": f"response from {name}"}]},
        [],
        "end_turn",
        MagicMock(input_tokens=100, output_tokens=50, provider=name, model="test-model"),
    ))
    provider.create_message = AsyncMock(return_value=("text", MagicMock()))
    provider.convert_tools = MagicMock(return_value=[])
    return provider


class ProviderStatusTests(unittest.TestCase):
    def test_initially_available(self) -> None:
        status = ProviderStatus()
        self.assertTrue(status.is_available())

    def test_mark_error_makes_unavailable(self) -> None:
        status = ProviderStatus()
        status.mark_error()
        self.assertFalse(status.available)
        self.assertEqual(status.consecutive_errors, 1)

    def test_mark_success_resets_errors(self) -> None:
        status = ProviderStatus()
        status.mark_error()
        status.mark_error()
        status.mark_success()
        self.assertTrue(status.available)
        self.assertEqual(status.consecutive_errors, 0)

    def test_cooldown_expires(self) -> None:
        status = ProviderStatus()
        status.mark_error()
        # Force cooldown to have expired
        status.cooldown_until = 0.0
        self.assertTrue(status.is_available())


class ProviderPoolTests(unittest.TestCase):
    def test_provider_names(self) -> None:
        p1 = _make_fake_provider("anthropic")
        p2 = _make_fake_provider("openai")
        pool = ProviderPool({"anthropic": p1, "openai": p2})
        self.assertEqual(sorted(pool.provider_names), ["anthropic", "openai"])

    def test_get_provider(self) -> None:
        p1 = _make_fake_provider()
        pool = ProviderPool({"anthropic": p1})
        self.assertIs(pool.get_provider("anthropic"), p1)
        self.assertIsNone(pool.get_provider("missing"))

    def test_resolve_target_existing(self) -> None:
        p1 = _make_fake_provider()
        pool = ProviderPool({"anthropic": p1})
        provider, model = pool.resolve_target(RoutingTarget("anthropic", "haiku"))
        self.assertIs(provider, p1)
        self.assertEqual(model, "haiku")

    def test_resolve_target_fallback(self) -> None:
        p1 = _make_fake_provider(family="openai")
        p2 = _make_fake_provider(family="openai")
        pool = ProviderPool(
            {"primary": p1, "secondary": p2},
            fallback_provider="primary",
        )
        # Mark secondary unavailable
        pool._status["secondary"].mark_error()
        pool._status["secondary"].cooldown_until = float("inf")
        provider, model = pool.resolve_target(RoutingTarget("secondary", "gpt-4o"))
        self.assertIs(provider, p1)  # Fell back to same-family primary

    def test_resolve_target_no_providers_raises(self) -> None:
        pool = ProviderPool({})
        with self.assertRaises(ValueError):
            pool.resolve_target(RoutingTarget("anthropic", "model"))

    def test_stream_chat_dispatches(self) -> None:
        p1 = _make_fake_provider("anthropic")
        pool = ProviderPool({"anthropic": p1})
        target = RoutingTarget("anthropic", "sonnet")

        asyncio.run(pool.stream_chat(
            target, 8192, 0.7, "system", [], [],
        ))
        p1.stream_chat.assert_called_once()
        self.assertEqual(pool.active_cache_provider, "anthropic")

    def test_stream_chat_fallback_on_error(self) -> None:
        p1 = _make_fake_provider("primary", family="openai")
        p2 = _make_fake_provider("secondary", family="openai")
        p1.stream_chat = AsyncMock(side_effect=RuntimeError("API error"))
        pool = ProviderPool(
            {"primary": p1, "secondary": p2},
            fallback_provider="secondary",
        )

        asyncio.run(pool.stream_chat(
            RoutingTarget("primary", "model"), 8192, 0.7, "sys", [], [],
        ))
        p2.stream_chat.assert_called_once()
        self.assertEqual(pool.active_cache_provider, "secondary")

    def test_convert_tools(self) -> None:
        p1 = _make_fake_provider()
        p1.convert_tools.return_value = [{"name": "tool1"}]
        pool = ProviderPool({"anthropic": p1}, fallback_provider="anthropic")
        result = pool.convert_tools([])
        self.assertEqual(result, [{"name": "tool1"}])

    def test_should_switch_provider_no_cache(self) -> None:
        p1 = _make_fake_provider()
        pool = ProviderPool({"anthropic": p1})
        # No active cache — always switch
        self.assertTrue(pool.should_switch_provider("openai", 1000, 3.0))

    def test_should_switch_provider_same_provider(self) -> None:
        p1 = _make_fake_provider()
        pool = ProviderPool({"anthropic": p1})
        pool._active_cache_provider = "anthropic"
        self.assertTrue(pool.should_switch_provider("anthropic", 0, 3.0))

    def test_should_switch_provider_penalty(self) -> None:
        p1 = _make_fake_provider()
        pool = ProviderPool(
            {"anthropic": p1},
            cache_switch_penalty_tokens=100000,
        )
        pool._active_cache_provider = "anthropic"
        # Small savings vs large penalty — should not switch
        self.assertFalse(pool.should_switch_provider("openai", 100, 3.0))

    def test_resolve_target_cross_family_no_fallback(self) -> None:
        """Cross-family fallback is not attempted — raises ValueError."""
        p1 = _make_fake_provider(family="anthropic")
        p2 = _make_fake_provider(family="openai")
        pool = ProviderPool(
            {"anthropic": p1, "ollama": p2},
            fallback_provider="anthropic",
        )
        # Mark ollama unavailable
        pool._status["ollama"].mark_error()
        pool._status["ollama"].cooldown_until = float("inf")
        with self.assertRaises(ValueError, msg="No same-family"):
            pool.resolve_target(RoutingTarget("ollama", "qwen2.5:7b"))

    def test_resolve_target_same_family_fallback(self) -> None:
        """Same-family fallback works when primary is unavailable."""
        p1 = _make_fake_provider(family="openai")
        p2 = _make_fake_provider(family="openai")
        pool = ProviderPool(
            {"openai": p1, "ollama": p2},
            fallback_provider="openai",
        )
        pool._status["ollama"].mark_error()
        pool._status["ollama"].cooldown_until = float("inf")
        provider, model = pool.resolve_target(RoutingTarget("ollama", "qwen2.5:7b"))
        self.assertIs(provider, p1)
        self.assertEqual(model, "qwen2.5:7b")

    def test_stream_chat_cross_family_no_fallback(self) -> None:
        """Cross-family fallback in stream_chat raises the original error."""
        p1 = _make_fake_provider("ollama", family="openai")
        p2 = _make_fake_provider("anthropic", family="anthropic")
        p1.stream_chat = AsyncMock(side_effect=RuntimeError("Ollama down"))
        pool = ProviderPool(
            {"ollama": p1, "anthropic": p2},
            fallback_provider="anthropic",
        )
        with self.assertRaises(RuntimeError, msg="Ollama down"):
            asyncio.run(pool.stream_chat(
                RoutingTarget("ollama", "qwen2.5:7b"), 8192, 0.7, "sys", [], [],
            ))
        # Anthropic provider should NOT have been called
        p2.stream_chat.assert_not_called()
