"""Tests for OllamaProvider — OpenAI-compatible local Ollama provider."""

from __future__ import annotations

import unittest
from typing import Any

from loguru import logger as _loguru_logger

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


class _LoguruCapture:
    """Capture loguru warnings into a list for assertions."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self._sink_id: int | None = None

    def __enter__(self) -> _LoguruCapture:
        def _sink(message: Any) -> None:
            rec = message.record
            self.records.append({"level": rec["level"].name, "message": rec["message"]})

        self._sink_id = _loguru_logger.add(_sink, level="WARNING")
        return self

    def __exit__(self, *_: Any) -> None:
        if self._sink_id is not None:
            _loguru_logger.remove(self._sink_id)

    @property
    def warning_messages(self) -> list[str]:
        return [r["message"] for r in self.records if r["level"] == "WARNING"]


class OllamaInspectAssistantMessageTests(unittest.TestCase):
    """Phase 2 of PLAN-gemma-model-support — gemma_unparsed.* metric detection."""

    def test_no_warning_when_tool_calls_already_parsed(self) -> None:
        provider = OllamaProvider(api_key="")
        with _LoguruCapture() as cap:
            provider._inspect_assistant_message(
                '```json\n{"name": "read_file", "arguments": {}}\n```',
                tool_calls_count=1,
            )
        self.assertEqual([], cap.warning_messages)

    def test_no_warning_on_plain_text(self) -> None:
        provider = OllamaProvider(api_key="")
        with _LoguruCapture() as cap:
            provider._inspect_assistant_message("Just chatting.", tool_calls_count=0)
        self.assertEqual([], cap.warning_messages)

    def test_no_warning_on_empty_text(self) -> None:
        provider = OllamaProvider(api_key="")
        with _LoguruCapture() as cap:
            provider._inspect_assistant_message("", tool_calls_count=0)
        self.assertEqual([], cap.warning_messages)

    def test_detects_fenced_json_with_explicit_lang(self) -> None:
        provider = OllamaProvider(api_key="")
        text = 'Sure, here it is:\n```json\n{"name": "read_file", "arguments": {"path": "a.py"}}\n```'
        with _LoguruCapture() as cap:
            provider._inspect_assistant_message(text, tool_calls_count=0)
        self.assertTrue(any("gemma_unparsed.fenced_json" in m for m in cap.warning_messages))

    def test_detects_fenced_json_without_lang_tag(self) -> None:
        provider = OllamaProvider(api_key="")
        text = '```\n{"name": "read_file", "arguments": {"path": "a.py"}}\n```'
        with _LoguruCapture() as cap:
            provider._inspect_assistant_message(text, tool_calls_count=0)
        self.assertTrue(any("gemma_unparsed.fenced_json" in m for m in cap.warning_messages))

    def test_detects_truncated_xml_tool_call(self) -> None:
        provider = OllamaProvider(api_key="")
        text = 'I will read the file.\n<tool_call>\n{"name": "read_file", "arguments": {"path": "a.py"'
        with _LoguruCapture() as cap:
            provider._inspect_assistant_message(text, tool_calls_count=0)
        self.assertTrue(any("gemma_unparsed.bare_xml" in m for m in cap.warning_messages))

    def test_closed_xml_tool_call_does_not_warn(self) -> None:
        """Well-formed <tool_call>...</tool_call> blocks should be parsed by
        Ollama upstream — even if tool_calls_count is 0 here, the bare_xml
        warning only fires for *unclosed* blocks."""
        provider = OllamaProvider(api_key="")
        text = '<tool_call>\n{"name": "read_file", "arguments": {}}\n</tool_call>'
        with _LoguruCapture() as cap:
            provider._inspect_assistant_message(text, tool_calls_count=0)
        self.assertFalse(any("gemma_unparsed.bare_xml" in m for m in cap.warning_messages))


if __name__ == "__main__":
    unittest.main()
