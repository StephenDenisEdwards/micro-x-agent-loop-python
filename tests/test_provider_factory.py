"""Tests for provider factory and DeepSeek provider."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from micro_x_agent_loop.provider import create_provider


class CreateProviderTests(unittest.TestCase):
    def test_anthropic_creates_provider(self) -> None:
        with patch("micro_x_agent_loop.providers.anthropic_provider.AnthropicProvider.__init__", return_value=None):
            p = create_provider("anthropic", "key1")
            self.assertIsNotNone(p)

    def test_openai_creates_provider(self) -> None:
        with patch("micro_x_agent_loop.providers.openai_provider.OpenAIProvider.__init__", return_value=None):
            p = create_provider("openai", "key1")
            self.assertIsNotNone(p)

    def test_deepseek_creates_provider(self) -> None:
        with patch("micro_x_agent_loop.providers.openai_provider.OpenAIProvider.__init__", return_value=None):
            p = create_provider("deepseek", "key1")
            self.assertIsNotNone(p)

    def test_gemini_creates_provider(self) -> None:
        with patch("micro_x_agent_loop.providers.gemini_provider.GeminiProvider.__init__", return_value=None):
            p = create_provider("gemini", "key1")
            self.assertIsNotNone(p)

    def test_unknown_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            create_provider("unknown", "key")
        self.assertIn("unknown", str(ctx.exception).lower())

    def test_case_insensitive(self) -> None:
        with patch("micro_x_agent_loop.providers.anthropic_provider.AnthropicProvider.__init__", return_value=None):
            p = create_provider("  Anthropic  ", "key1")
            self.assertIsNotNone(p)


class DeepSeekExtractCachedTokensTests(unittest.TestCase):
    def test_top_level_field(self) -> None:
        from micro_x_agent_loop.providers.deepseek_provider import DeepSeekProvider

        provider = DeepSeekProvider.__new__(DeepSeekProvider)
        usage = MagicMock()
        usage.prompt_cache_hit_tokens = 42
        self.assertEqual(42, provider._extract_cached_tokens(usage))

    def test_fallback_to_parent(self) -> None:
        from micro_x_agent_loop.providers.deepseek_provider import DeepSeekProvider

        provider = DeepSeekProvider.__new__(DeepSeekProvider)
        usage = MagicMock(spec=[])  # No attributes at all
        del usage.prompt_cache_hit_tokens
        # Parent method should handle gracefully
        with patch.object(type(provider).__bases__[0], "_extract_cached_tokens", return_value=99):
            result = provider._extract_cached_tokens(usage)
        self.assertEqual(99, result)


if __name__ == "__main__":
    unittest.main()
