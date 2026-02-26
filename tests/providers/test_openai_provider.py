import asyncio
import json
import unittest
from types import SimpleNamespace

from micro_x_agent_loop.providers.openai_provider import (
    _STOP_REASON_MAP,
    OpenAIProvider,
    _to_openai_messages,
    _to_openai_tools,
)
from micro_x_agent_loop.usage import UsageResult
from tests.fakes import FakeTool


class ToOpenAIMessagesTests(unittest.TestCase):
    def test_system_prompt_becomes_system_message(self) -> None:
        result = _to_openai_messages("You are helpful.", [])
        self.assertEqual(1, len(result))
        self.assertEqual("system", result[0]["role"])
        self.assertEqual("You are helpful.", result[0]["content"])

    def test_user_string_content(self) -> None:
        result = _to_openai_messages("", [{"role": "user", "content": "hello"}])
        self.assertEqual(1, len(result))
        self.assertEqual("user", result[0]["role"])
        self.assertEqual("hello", result[0]["content"])

    def test_assistant_text_blocks(self) -> None:
        result = _to_openai_messages("", [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "line1"},
                    {"type": "text", "text": "line2"},
                ],
            }
        ])
        self.assertEqual(1, len(result))
        self.assertEqual("assistant", result[0]["role"])
        self.assertEqual("line1\nline2", result[0]["content"])

    def test_assistant_tool_use_blocks(self) -> None:
        result = _to_openai_messages("", [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll read that file."},
                    {
                        "type": "tool_use",
                        "id": "call_abc",
                        "name": "read_file",
                        "input": {"path": "test.py"},
                    },
                ],
            }
        ])
        self.assertEqual(1, len(result))
        msg = result[0]
        self.assertEqual("assistant", msg["role"])
        self.assertEqual("I'll read that file.", msg["content"])
        self.assertEqual(1, len(msg["tool_calls"]))
        tc = msg["tool_calls"][0]
        self.assertEqual("call_abc", tc["id"])
        self.assertEqual("function", tc["type"])
        self.assertEqual("read_file", tc["function"]["name"])
        self.assertEqual(json.dumps({"path": "test.py"}), tc["function"]["arguments"])

    def test_user_tool_result_blocks(self) -> None:
        result = _to_openai_messages("", [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_abc",
                        "content": "file contents here",
                    },
                ],
            }
        ])
        self.assertEqual(1, len(result))
        msg = result[0]
        self.assertEqual("tool", msg["role"])
        self.assertEqual("call_abc", msg["tool_call_id"])
        self.assertEqual("file contents here", msg["content"])

    def test_user_mixed_text_and_tool_results(self) -> None:
        result = _to_openai_messages("", [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Here are results:"},
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_1",
                        "content": "result1",
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_2",
                        "content": "result2",
                    },
                ],
            }
        ])
        # Should produce: tool msg for call_1, tool msg for call_2, user msg for text
        tool_msgs = [m for m in result if m["role"] == "tool"]
        user_msgs = [m for m in result if m["role"] == "user"]
        self.assertEqual(2, len(tool_msgs))
        self.assertEqual(1, len(user_msgs))
        self.assertEqual("Here are results:", user_msgs[0]["content"])

    def test_tool_result_with_list_content(self) -> None:
        result = _to_openai_messages("", [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_x",
                        "content": [{"type": "text", "text": "part1"}, {"type": "text", "text": "part2"}],
                    },
                ],
            }
        ])
        self.assertEqual(1, len(result))
        self.assertEqual("part1\npart2", result[0]["content"])


class ToOpenAIToolsTests(unittest.TestCase):
    def test_converts_internal_tools_to_openai_format(self) -> None:
        internal_tools = [
            {
                "name": "read_file",
                "description": "Read a file",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            }
        ]
        result = _to_openai_tools(internal_tools)
        self.assertEqual(1, len(result))
        self.assertEqual("function", result[0]["type"])
        func = result[0]["function"]
        self.assertEqual("read_file", func["name"])
        self.assertEqual("Read a file", func["description"])
        self.assertIn("properties", func["parameters"])


class StopReasonMapTests(unittest.TestCase):
    def test_stop_maps_to_end_turn(self) -> None:
        self.assertEqual("end_turn", _STOP_REASON_MAP["stop"])

    def test_tool_calls_maps_to_tool_use(self) -> None:
        self.assertEqual("tool_use", _STOP_REASON_MAP["tool_calls"])

    def test_length_maps_to_max_tokens(self) -> None:
        self.assertEqual("max_tokens", _STOP_REASON_MAP["length"])


class OpenAIProviderConvertToolsTests(unittest.TestCase):
    def test_convert_tools(self) -> None:
        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider._client = None  # not used for convert_tools
        tools = [
            FakeTool("write_file", "Write a file", {"type": "object", "properties": {"path": {"type": "string"}}}),
        ]
        result = provider.convert_tools(tools)
        self.assertEqual(1, len(result))
        self.assertEqual("write_file", result[0]["name"])
        self.assertEqual("Write a file", result[0]["description"])


class OpenAIProviderStreamTests(unittest.TestCase):
    def _make_provider(self, chunks: list) -> OpenAIProvider:
        provider = OpenAIProvider.__new__(OpenAIProvider)

        class _FakeStream:
            def __init__(self, chunks):
                self._chunks = chunks

            def __aiter__(self):
                self._iter = iter(self._chunks)
                return self

            async def __anext__(self):
                try:
                    return next(self._iter)
                except StopIteration as exc:
                    raise StopAsyncIteration from exc

        class _FakeCompletions:
            def __init__(self, chunks):
                self._chunks = chunks

            async def create(self, **kwargs):
                return _FakeStream(self._chunks)

        class _FakeChat:
            def __init__(self, chunks):
                self.completions = _FakeCompletions(chunks)

        class _FakeClient:
            def __init__(self, chunks):
                self.chat = _FakeChat(chunks)

        provider._client = _FakeClient(chunks)
        return provider

    def _usage_chunk(self, prompt_tokens=10, completion_tokens=5):
        """Create a usage-only chunk (final chunk with stream_options)."""
        return SimpleNamespace(
            choices=[],
            usage=SimpleNamespace(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                prompt_tokens_details=None,
            ),
        )

    def test_stream_chat_text_response(self) -> None:
        chunks = [
            SimpleNamespace(choices=[
                SimpleNamespace(
                    finish_reason=None,
                    delta=SimpleNamespace(content="Hello", tool_calls=None),
                )
            ], usage=None),
            SimpleNamespace(choices=[
                SimpleNamespace(
                    finish_reason=None,
                    delta=SimpleNamespace(content=" world", tool_calls=None),
                )
            ], usage=None),
            SimpleNamespace(choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    delta=SimpleNamespace(content=None, tool_calls=None),
                )
            ], usage=None),
            self._usage_chunk(prompt_tokens=15, completion_tokens=3),
        ]
        provider = self._make_provider(chunks)

        message, tool_use_blocks, stop_reason, usage = asyncio.run(
            provider.stream_chat("gpt-4o", 100, 0.5, "sys", [{"role": "user", "content": "hi"}], [])
        )

        self.assertEqual("assistant", message["role"])
        self.assertEqual("end_turn", stop_reason)
        self.assertEqual([], tool_use_blocks)
        self.assertEqual("Hello world", message["content"][0]["text"])
        self.assertIsInstance(usage, UsageResult)
        self.assertEqual(15, usage.input_tokens)
        self.assertEqual(3, usage.output_tokens)
        self.assertEqual("openai", usage.provider)

    def test_stream_chat_tool_call_response(self) -> None:
        chunks = [
            SimpleNamespace(choices=[
                SimpleNamespace(
                    finish_reason=None,
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id="call_123",
                                function=SimpleNamespace(name="read_file", arguments='{"pa'),
                            )
                        ],
                    ),
                )
            ], usage=None),
            SimpleNamespace(choices=[
                SimpleNamespace(
                    finish_reason=None,
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id=None,
                                function=SimpleNamespace(name=None, arguments='th": "x"}'),
                            )
                        ],
                    ),
                )
            ], usage=None),
            SimpleNamespace(choices=[
                SimpleNamespace(
                    finish_reason="tool_calls",
                    delta=SimpleNamespace(content=None, tool_calls=None),
                )
            ], usage=None),
            self._usage_chunk(),
        ]
        provider = self._make_provider(chunks)

        message, tool_use_blocks, stop_reason, usage = asyncio.run(
            provider.stream_chat("gpt-4o", 100, 0.5, "sys", [{"role": "user", "content": "hi"}], [])
        )

        self.assertEqual("tool_use", stop_reason)
        self.assertEqual(1, len(tool_use_blocks))
        self.assertEqual("read_file", tool_use_blocks[0]["name"])
        self.assertEqual({"path": "x"}, tool_use_blocks[0]["input"])
        self.assertEqual("call_123", tool_use_blocks[0]["id"])
        self.assertIsInstance(usage, UsageResult)

    def test_stream_chat_text_and_tool_calls(self) -> None:
        chunks = [
            SimpleNamespace(choices=[
                SimpleNamespace(
                    finish_reason=None,
                    delta=SimpleNamespace(content="Let me read that.", tool_calls=None),
                )
            ], usage=None),
            SimpleNamespace(choices=[
                SimpleNamespace(
                    finish_reason=None,
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id="call_456",
                                function=SimpleNamespace(name="read_file", arguments='{"path": "a.py"}'),
                            )
                        ],
                    ),
                )
            ], usage=None),
            SimpleNamespace(choices=[
                SimpleNamespace(
                    finish_reason="tool_calls",
                    delta=SimpleNamespace(content=None, tool_calls=None),
                )
            ], usage=None),
            self._usage_chunk(),
        ]
        provider = self._make_provider(chunks)

        message, tool_use_blocks, stop_reason, usage = asyncio.run(
            provider.stream_chat("gpt-4o", 100, 0.5, "sys", [{"role": "user", "content": "hi"}], [])
        )

        self.assertEqual("tool_use", stop_reason)
        self.assertEqual(1, len(tool_use_blocks))
        # Should have both text and tool_use blocks in content
        self.assertEqual(2, len(message["content"]))
        self.assertEqual("text", message["content"][0]["type"])
        self.assertEqual("Let me read that.", message["content"][0]["text"])
        self.assertEqual("tool_use", message["content"][1]["type"])
        self.assertIsInstance(usage, UsageResult)

    def test_stream_chat_length_stop_reason(self) -> None:
        chunks = [
            SimpleNamespace(choices=[
                SimpleNamespace(
                    finish_reason="length",
                    delta=SimpleNamespace(content="truncated", tool_calls=None),
                )
            ], usage=None),
            self._usage_chunk(),
        ]
        provider = self._make_provider(chunks)

        _, _, stop_reason, usage = asyncio.run(
            provider.stream_chat("gpt-4o", 100, 0.5, "sys", [{"role": "user", "content": "hi"}], [])
        )

        self.assertEqual("max_tokens", stop_reason)
        self.assertIsInstance(usage, UsageResult)

    def test_stream_chat_multiple_tool_calls(self) -> None:
        chunks = [
            SimpleNamespace(choices=[
                SimpleNamespace(
                    finish_reason=None,
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id="call_a",
                                function=SimpleNamespace(name="read_file", arguments='{"path": "a.py"}'),
                            ),
                        ],
                    ),
                )
            ], usage=None),
            SimpleNamespace(choices=[
                SimpleNamespace(
                    finish_reason=None,
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=1,
                                id="call_b",
                                function=SimpleNamespace(
                                    name="write_file", arguments='{"path": "b.py", "content": "x"}'
                                ),
                            ),
                        ],
                    ),
                )
            ], usage=None),
            SimpleNamespace(choices=[
                SimpleNamespace(
                    finish_reason="tool_calls",
                    delta=SimpleNamespace(content=None, tool_calls=None),
                )
            ], usage=None),
            self._usage_chunk(),
        ]
        provider = self._make_provider(chunks)

        message, tool_use_blocks, stop_reason, usage = asyncio.run(
            provider.stream_chat("gpt-4o", 100, 0.5, "sys", [{"role": "user", "content": "hi"}], [])
        )

        self.assertEqual("tool_use", stop_reason)
        self.assertEqual(2, len(tool_use_blocks))
        self.assertEqual("read_file", tool_use_blocks[0]["name"])
        self.assertEqual("write_file", tool_use_blocks[1]["name"])
        self.assertIsInstance(usage, UsageResult)


if __name__ == "__main__":
    unittest.main()
