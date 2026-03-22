"""Tests for provider_pool module."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from micro_x_agent_loop.provider_pool import ProviderPool, ProviderStatus, RoutingTarget


def _make_fake_provider(name: str = "fake") -> MagicMock:
    """Create a fake provider with async methods."""
    provider = MagicMock()
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
        p1 = _make_fake_provider()
        p2 = _make_fake_provider()
        pool = ProviderPool(
            {"anthropic": p1, "openai": p2},
            fallback_provider="anthropic",
        )
        # Mark openai unavailable
        pool._status["openai"].mark_error()
        pool._status["openai"].cooldown_until = float("inf")
        provider, model = pool.resolve_target(RoutingTarget("openai", "gpt-4o"))
        self.assertIs(provider, p1)  # Fell back to anthropic

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
        p1 = _make_fake_provider("anthropic")
        p2 = _make_fake_provider("openai")
        p1.stream_chat = AsyncMock(side_effect=RuntimeError("API error"))
        pool = ProviderPool(
            {"anthropic": p1, "openai": p2},
            fallback_provider="openai",
        )

        asyncio.run(pool.stream_chat(
            RoutingTarget("anthropic", "model"), 8192, 0.7, "sys", [], [],
        ))
        p2.stream_chat.assert_called_once()
        self.assertEqual(pool.active_cache_provider, "openai")

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
