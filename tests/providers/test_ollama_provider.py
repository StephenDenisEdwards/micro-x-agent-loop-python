"""Tests for OllamaProvider — OpenAI-compatible local Ollama provider."""

from __future__ import annotations

import unittest

from micro_x_agent_loop.providers.ollama_provider import OllamaProvider


class OllamaProviderInitTests(unittest.TestCase):
    def test_default_base_url(self) -> None:
        provider = OllamaProvider(api_key="")
        url_str = str(provider._client.base_url)
        self.assertIn("localhost", url_str)
        self.assertIn("11434", url_str)
        self.assertIn("/v1", url_str)

    def test_custom_base_url(self) -> None:
        provider = OllamaProvider(api_key="", base_url="http://myhost:1234")
        url_str = str(provider._client.base_url)
        self.assertIn("myhost", url_str)
        self.assertIn("/v1", url_str)

    def test_custom_base_url_trailing_slash(self) -> None:
        provider = OllamaProvider(api_key="", base_url="http://myhost:1234/")
        url_str = str(provider._client.base_url)
        self.assertIn("/v1", url_str)
        # Should not have double /v1
        self.assertNotIn("/v1/v1", url_str)

    def test_api_key_defaults_to_ollama(self) -> None:
        provider = OllamaProvider(api_key="")
        self.assertEqual("ollama", provider._client.api_key)

    def test_explicit_api_key_used(self) -> None:
        provider = OllamaProvider(api_key="my-key")
        self.assertEqual("my-key", provider._client.api_key)

    def test_family_is_openai(self) -> None:
        """OllamaProvider inherits OpenAI family since it's API-compatible."""
        provider = OllamaProvider(api_key="")
        self.assertEqual("openai", provider.family)


class OllamaBuildStreamKwargsTests(unittest.TestCase):
    def test_tool_choice_auto_when_tools_present(self) -> None:
        provider = OllamaProvider(api_key="")
        kwargs = provider._build_stream_kwargs(
            model="qwen2.5:7b",
            max_tokens=1024,
            temperature=0.5,
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "test"}}],
        )
        self.assertEqual("auto", kwargs["tool_choice"])
        self.assertIn("tools", kwargs)

    def test_no_tool_choice_without_tools(self) -> None:
        provider = OllamaProvider(api_key="")
        kwargs = provider._build_stream_kwargs(
            model="qwen2.5:7b",
            max_tokens=1024,
            temperature=0.5,
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
        )
        self.assertNotIn("tool_choice", kwargs)
        self.assertNotIn("tools", kwargs)

    def test_inherits_stream_options(self) -> None:
        provider = OllamaProvider(api_key="")
        kwargs = provider._build_stream_kwargs(
            model="qwen2.5:7b",
            max_tokens=1024,
            temperature=0.5,
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
        )
        self.assertTrue(kwargs["stream"])
        self.assertEqual({"include_usage": True}, kwargs["stream_options"])

    def test_provider_name_is_ollama(self) -> None:
        provider = OllamaProvider(api_key="")
        self.assertEqual("ollama", provider._provider_name)


if __name__ == "__main__":
    unittest.main()
