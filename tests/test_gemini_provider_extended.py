"""Extended tests for Gemini provider — covers stream_chat, create_message, and edge cases."""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Mock google.genai.types — shared across all tests
# ---------------------------------------------------------------------------

_mock_types = MagicMock()


def _make_part(**kwargs):
    p = MagicMock()
    for k, v in kwargs.items():
        setattr(p, k, v)
    return p


_mock_types.Part = _make_part
_mock_types.Content = lambda role, parts: MagicMock(role=role, parts=parts)
_mock_types.FunctionCall = lambda name, args: MagicMock(name=name, args=args)
_mock_types.FunctionResponse = lambda name, response: MagicMock(name=name, response=response)
_mock_types.FunctionDeclaration = lambda name, description, parameters: MagicMock(
    name=name, description=description, parameters=parameters
)
_mock_types.Tool = lambda function_declarations: MagicMock(function_declarations=function_declarations)
_mock_types.GenerateContentConfig = MagicMock()
_mock_types.AutomaticFunctionCallingConfig = MagicMock()


def _load_gemini_provider():
    """Import gemini_provider with mocked google.genai. Safe for repeated calls."""
    import importlib

    mocks = {
        "google": MagicMock(),
        "google.genai": MagicMock(),
        "google.genai.types": _mock_types,
    }
    with patch.dict("sys.modules", mocks):
        # Ensure a fresh import by removing the cached module
        sys.modules.pop("micro_x_agent_loop.providers.gemini_provider", None)
        from micro_x_agent_loop.providers import gemini_provider
        importlib.reload(gemini_provider)
        return gemini_provider


# Pre-load the module once at import time with mocking
_gp = _load_gemini_provider()


class GeminiStopReasonMapTests(unittest.TestCase):
    def test_stop_maps(self) -> None:
        m = _gp._STOP_REASON_MAP
        self.assertEqual("end_turn", m["STOP"])
        self.assertEqual("max_tokens", m["MAX_TOKENS"])
        self.assertEqual("end_turn", m["FINISH_REASON_UNSPECIFIED"])
        self.assertEqual("end_turn", m["OTHER"])


class ToGeminiContentsExtendedTests(unittest.TestCase):
    def test_user_list_content_with_tool_result(self) -> None:
        with patch("google.genai.types", _mock_types):
            messages = [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "tu_1", "name": "search", "input": {}},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tu_1", "content": "result text"},
                        {"type": "text", "text": "also this"},
                    ],
                },
            ]
            result = _gp._to_gemini_contents(messages)
            self.assertEqual(2, len(result))

    def test_user_list_with_tool_result_list_content(self) -> None:
        with patch("google.genai.types", _mock_types):
            messages = [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "tu_1", "name": "search", "input": {}},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tu_1",
                            "content": [
                                {"type": "text", "text": "line 1"},
                                {"type": "text", "text": "line 2"},
                            ],
                        },
                    ],
                },
            ]
            result = _gp._to_gemini_contents(messages)
            self.assertEqual(2, len(result))

    def test_assistant_string_content(self) -> None:
        with patch("google.genai.types", _mock_types):
            messages = [{"role": "assistant", "content": "just text"}]
            result = _gp._to_gemini_contents(messages)
            self.assertEqual(1, len(result))

    def test_empty_text_blocks_skipped(self) -> None:
        with patch("google.genai.types", _mock_types):
            messages = [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": ""},
                        {"type": "text", "text": "actual content"},
                    ],
                },
            ]
            result = _gp._to_gemini_contents(messages)
            self.assertEqual(1, len(result))

    def test_empty_user_string_skipped(self) -> None:
        with patch("google.genai.types", _mock_types):
            messages = [{"role": "user", "content": ""}]
            result = _gp._to_gemini_contents(messages)
            self.assertEqual(0, len(result))

    def test_user_list_with_string_blocks(self) -> None:
        with patch("google.genai.types", _mock_types):
            messages = [
                {"role": "user", "content": ["hello", "world"]},
            ]
            result = _gp._to_gemini_contents(messages)
            self.assertEqual(1, len(result))

    def test_non_dict_blocks_skipped_in_assistant(self) -> None:
        with patch("google.genai.types", _mock_types):
            messages = [
                {
                    "role": "assistant",
                    "content": ["just a string", {"type": "text", "text": "real block"}],
                },
            ]
            result = _gp._to_gemini_contents(messages)
            self.assertEqual(1, len(result))


class GeminiStreamChatTests(unittest.TestCase):
    def test_stream_chat_text_only(self) -> None:
        with patch("google.genai.types", _mock_types):
            chunk = MagicMock()
            chunk.text = "Hello world"
            chunk.function_calls = None
            candidate = MagicMock()
            fr = MagicMock()
            fr.name = "STOP"
            candidate.finish_reason = fr
            chunk.candidates = [candidate]
            usage = MagicMock()
            usage.prompt_token_count = 10
            usage.candidates_token_count = 5
            usage.cached_content_token_count = 0
            chunk.usage_metadata = usage

            async def mock_stream():
                yield chunk

            mock_client = MagicMock()
            mock_client.aio.models.generate_content_stream = AsyncMock(return_value=mock_stream())

            provider = _gp.GeminiProvider.__new__(_gp.GeminiProvider)
            provider._client = mock_client

            msg, tool_blocks, stop_reason, usage_result = asyncio.run(
                provider.stream_chat(
                    model="gemini-2.5-pro",
                    max_tokens=1024,
                    temperature=0.5,
                    system_prompt="be helpful",
                    messages=[{"role": "user", "content": "hi"}],
                    tools=[],
                )
            )

            self.assertEqual("assistant", msg["role"])
            self.assertEqual("Hello world", msg["content"][0]["text"])
            self.assertEqual([], tool_blocks)
            self.assertEqual("end_turn", stop_reason)
            self.assertEqual(10, usage_result.input_tokens)
            self.assertEqual(5, usage_result.output_tokens)

    def test_stream_chat_with_tool_calls(self) -> None:
        with patch("google.genai.types", _mock_types):
            fc = MagicMock()
            fc.name = "read_file"
            fc.args = {"path": "test.py"}

            chunk = MagicMock()
            chunk.text = None
            chunk.function_calls = [fc]
            chunk.candidates = []
            chunk.usage_metadata = MagicMock(
                prompt_token_count=15, candidates_token_count=8, cached_content_token_count=0
            )

            async def mock_stream():
                yield chunk

            mock_client = MagicMock()
            mock_client.aio.models.generate_content_stream = AsyncMock(return_value=mock_stream())

            provider = _gp.GeminiProvider.__new__(_gp.GeminiProvider)
            provider._client = mock_client

            msg, tool_blocks, stop_reason, usage_result = asyncio.run(
                provider.stream_chat(
                    model="gemini-2.5-pro",
                    max_tokens=1024,
                    temperature=0.5,
                    system_prompt="",
                    messages=[{"role": "user", "content": "read test.py"}],
                    tools=[{"name": "read_file", "description": "Read file", "input_schema": {}}],
                )
            )

            self.assertEqual("tool_use", stop_reason)
            self.assertEqual(1, len(tool_blocks))
            self.assertEqual("read_file", tool_blocks[0]["name"])

    def test_stream_chat_emits_text_delta(self) -> None:
        with patch("google.genai.types", _mock_types):
            chunk = MagicMock()
            chunk.text = "delta text"
            chunk.function_calls = None
            chunk.candidates = []
            chunk.usage_metadata = MagicMock(
                prompt_token_count=5, candidates_token_count=3, cached_content_token_count=0
            )

            async def mock_stream():
                yield chunk

            mock_client = MagicMock()
            mock_client.aio.models.generate_content_stream = AsyncMock(return_value=mock_stream())

            channel = MagicMock()
            provider = _gp.GeminiProvider.__new__(_gp.GeminiProvider)
            provider._client = mock_client

            asyncio.run(
                provider.stream_chat(
                    model="gemini-2.5-pro",
                    max_tokens=1024,
                    temperature=0.5,
                    system_prompt="",
                    messages=[{"role": "user", "content": "hi"}],
                    tools=[],
                    channel=channel,
                )
            )

            channel.emit_text_delta.assert_called_once_with("delta text")


class GeminiCreateMessageTests(unittest.TestCase):
    def test_create_message(self) -> None:
        with patch("google.genai.types", _mock_types):
            response = MagicMock()
            response.text = "summary text"
            response.usage_metadata = MagicMock(
                prompt_token_count=20, candidates_token_count=10, cached_content_token_count=2
            )

            mock_client = MagicMock()
            mock_client.aio.models.generate_content = AsyncMock(return_value=response)

            provider = _gp.GeminiProvider.__new__(_gp.GeminiProvider)
            provider._client = mock_client

            text, usage = asyncio.run(
                provider.create_message(
                    model="gemini-2.5-pro",
                    max_tokens=1024,
                    temperature=0.0,
                    messages=[{"role": "user", "content": "summarize"}],
                )
            )

            self.assertEqual("summary text", text)
            self.assertEqual(20, usage.input_tokens)
            self.assertEqual(10, usage.output_tokens)
            self.assertEqual(2, usage.cache_read_input_tokens)

    def test_create_message_none_text(self) -> None:
        with patch("google.genai.types", _mock_types):
            response = MagicMock()
            response.text = None
            response.usage_metadata = MagicMock(
                prompt_token_count=5, candidates_token_count=0, cached_content_token_count=0
            )

            mock_client = MagicMock()
            mock_client.aio.models.generate_content = AsyncMock(return_value=response)

            provider = _gp.GeminiProvider.__new__(_gp.GeminiProvider)
            provider._client = mock_client

            text, usage = asyncio.run(
                provider.create_message(
                    model="gemini-2.5-pro",
                    max_tokens=1024,
                    temperature=0.0,
                    messages=[{"role": "user", "content": "hi"}],
                )
            )

            self.assertEqual("", text)


class GeminiConvertToolsTests(unittest.TestCase):
    def test_convert_tools(self) -> None:
        from tests.fakes import FakeTool
        provider = _gp.GeminiProvider.__new__(_gp.GeminiProvider)
        tools = [FakeTool(name="test", description="a test tool")]
        result = provider.convert_tools(tools)
        self.assertEqual(1, len(result))
        self.assertEqual("test", result[0]["name"])

    def test_family(self) -> None:
        provider = _gp.GeminiProvider.__new__(_gp.GeminiProvider)
        self.assertEqual("gemini", provider.family)


if __name__ == "__main__":
    unittest.main()
