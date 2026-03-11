"""Tests for OpenAIProvider and helper functions."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from micro_x_agent_loop.providers.openai_provider import (
    OpenAIProvider,
    _to_openai_messages,
    _to_openai_tools,
)


class ToOpenAiMessagesTests(unittest.TestCase):
    def test_empty_messages(self) -> None:
        result = _to_openai_messages("", [])
        self.assertEqual([], result)

    def test_system_prompt_prepended(self) -> None:
        result = _to_openai_messages("You are helpful.", [])
        self.assertEqual(1, len(result))
        self.assertEqual("system", result[0]["role"])
        self.assertEqual("You are helpful.", result[0]["content"])

    def test_user_message_string(self) -> None:
        result = _to_openai_messages("", [{"role": "user", "content": "hello"}])
        self.assertEqual(1, len(result))
        self.assertEqual("user", result[0]["role"])
        self.assertEqual("hello", result[0]["content"])

    def test_assistant_message_string(self) -> None:
        result = _to_openai_messages("", [{"role": "assistant", "content": "reply"}])
        self.assertEqual(1, len(result))
        self.assertEqual("assistant", result[0]["role"])
        self.assertEqual("reply", result[0]["content"])

    def test_assistant_message_with_tool_use(self) -> None:
        msg = {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "I'll call the tool"},
                {
                    "type": "tool_use",
                    "id": "tid1",
                    "name": "search",
                    "input": {"query": "foo"},
                },
            ],
        }
        result = _to_openai_messages("", [msg])
        self.assertEqual(1, len(result))
        out = result[0]
        self.assertEqual("assistant", out["role"])
        self.assertEqual("I'll call the tool", out["content"])
        self.assertEqual(1, len(out["tool_calls"]))
        tc = out["tool_calls"][0]
        self.assertEqual("function", tc["type"])
        self.assertEqual("search", tc["function"]["name"])
        self.assertEqual({"query": "foo"}, json.loads(tc["function"]["arguments"]))

    def test_assistant_message_tool_only(self) -> None:
        msg = {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tid2",
                    "name": "run",
                    "input": {},
                }
            ],
        }
        result = _to_openai_messages("", [msg])
        self.assertIsNone(result[0]["content"])

    def test_user_message_with_tool_result(self) -> None:
        msg = {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tid1",
                    "content": "result text",
                }
            ],
        }
        result = _to_openai_messages("", [msg])
        self.assertEqual(1, len(result))
        self.assertEqual("tool", result[0]["role"])
        self.assertEqual("tid1", result[0]["tool_call_id"])
        self.assertEqual("result text", result[0]["content"])

    def test_user_message_with_tool_result_list_content(self) -> None:
        msg = {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tid2",
                    "content": [
                        {"type": "text", "text": "part1"},
                        {"type": "text", "text": "part2"},
                    ],
                }
            ],
        }
        result = _to_openai_messages("", [msg])
        self.assertEqual(1, len(result))
        self.assertIn("part1", result[0]["content"])
        self.assertIn("part2", result[0]["content"])

    def test_user_message_text_block(self) -> None:
        msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": "hello world"},
            ],
        }
        result = _to_openai_messages("", [msg])
        self.assertEqual(1, len(result))
        self.assertEqual("hello world", result[0]["content"])

    def test_other_role_pass_through(self) -> None:
        msg = {"role": "system", "content": "custom system"}
        result = _to_openai_messages("", [msg])
        self.assertEqual("system", result[0]["role"])


class ToOpenAiToolsTests(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertEqual([], _to_openai_tools([]))

    def test_single_tool(self) -> None:
        result = _to_openai_tools([
            {"name": "search", "description": "Search web", "input_schema": {"type": "object"}},
        ])
        self.assertEqual(1, len(result))
        t = result[0]
        self.assertEqual("function", t["type"])
        self.assertEqual("search", t["function"]["name"])
        self.assertEqual("Search web", t["function"]["description"])

    def test_tool_without_description(self) -> None:
        result = _to_openai_tools([{"name": "noop", "input_schema": {}}])
        self.assertEqual("", result[0]["function"]["description"])


def _make_chunk(*, content: str | None = None, tool_calls=None,
                finish_reason: str | None = None, usage=None):
    """Build a mock streaming chunk."""
    chunk = MagicMock()
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = tool_calls or []
    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish_reason
    chunk.choices = [choice]
    chunk.usage = usage
    return chunk


class OpenAIProviderStreamChatTests(unittest.TestCase):
    def _make_provider(self) -> OpenAIProvider:
        with patch("openai.AsyncOpenAI"):
            return OpenAIProvider(api_key="test")

    def test_simple_text_response(self) -> None:
        async def go():
            provider = self._make_provider()

            chunks = [
                _make_chunk(content="Hello"),
                _make_chunk(content=" world", finish_reason="stop"),
            ]

            async def fake_aiter(*a, **kw):
                for c in chunks:
                    yield c

            mock_stream = MagicMock()
            mock_stream.__aiter__ = fake_aiter

            provider._client.chat.completions.create = AsyncMock(return_value=mock_stream)

            msg, tool_blocks, stop_reason, usage = await provider.stream_chat(
                model="gpt-4",
                max_tokens=1000,
                temperature=0.0,
                system_prompt="sys",
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
            )

            self.assertEqual("end_turn", stop_reason)
            self.assertEqual("Hello world", msg["content"][0]["text"])
            self.assertEqual([], tool_blocks)

        asyncio.run(go())

    def test_tool_call_response(self) -> None:
        async def go():
            provider = self._make_provider()

            tc_delta = MagicMock()
            tc_delta.index = 0
            tc_delta.id = "call1"
            fn = MagicMock()
            fn.name = "search"
            fn.arguments = '{"q":"foo"}'
            tc_delta.function = fn

            chunks = [
                _make_chunk(tool_calls=[tc_delta], finish_reason="tool_calls"),
            ]

            async def fake_aiter(*a, **kw):
                for c in chunks:
                    yield c

            mock_stream = MagicMock()
            mock_stream.__aiter__ = fake_aiter
            provider._client.chat.completions.create = AsyncMock(return_value=mock_stream)

            msg, tool_blocks, stop_reason, usage = await provider.stream_chat(
                "gpt-4", 1000, 0.0, "", [{"role": "user", "content": "hi"}], []
            )

            self.assertEqual("tool_use", stop_reason)
            self.assertEqual(1, len(tool_blocks))
            self.assertEqual("search", tool_blocks[0]["name"])
            self.assertEqual({"q": "foo"}, tool_blocks[0]["input"])

        asyncio.run(go())

    def test_usage_extracted(self) -> None:
        async def go():
            provider = self._make_provider()

            usage = MagicMock()
            usage.prompt_tokens = 100
            usage.completion_tokens = 50
            usage.prompt_tokens_details = None

            chunks = [
                _make_chunk(finish_reason="stop", usage=usage),
            ]

            async def fake_aiter(*a, **kw):
                for c in chunks:
                    yield c

            mock_stream = MagicMock()
            mock_stream.__aiter__ = fake_aiter
            provider._client.chat.completions.create = AsyncMock(return_value=mock_stream)

            _, _, _, result_usage = await provider.stream_chat(
                "gpt-4", 1000, 0.0, "", [], []
            )

            self.assertEqual(100, result_usage.input_tokens)
            self.assertEqual(50, result_usage.output_tokens)

        asyncio.run(go())

    def test_channel_emits_text_delta(self) -> None:
        async def go():
            provider = self._make_provider()
            deltas: list[str] = []
            channel = MagicMock()
            channel.emit_text_delta.side_effect = deltas.append

            chunks = [_make_chunk(content="hi", finish_reason="stop")]

            async def fake_aiter(*a, **kw):
                for c in chunks:
                    yield c

            mock_stream = MagicMock()
            mock_stream.__aiter__ = fake_aiter
            provider._client.chat.completions.create = AsyncMock(return_value=mock_stream)

            await provider.stream_chat("m", 100, 0.0, "", [], [], channel=channel)
            self.assertEqual(["hi"], deltas)

        asyncio.run(go())

    def test_empty_choices_skipped(self) -> None:
        async def go():
            provider = self._make_provider()

            empty_chunk = MagicMock()
            empty_chunk.choices = []
            empty_chunk.usage = None
            normal_chunk = _make_chunk(content="ok", finish_reason="stop")

            async def fake_aiter(*a, **kw):
                for c in [empty_chunk, normal_chunk]:
                    yield c

            mock_stream = MagicMock()
            mock_stream.__aiter__ = fake_aiter
            provider._client.chat.completions.create = AsyncMock(return_value=mock_stream)

            msg, _, _, _ = await provider.stream_chat("m", 100, 0.0, "", [], [])
            self.assertEqual("ok", msg["content"][0]["text"])

        asyncio.run(go())

    def test_tools_included_when_provided(self) -> None:
        async def go():
            provider = self._make_provider()
            chunks = [_make_chunk(finish_reason="stop")]

            async def fake_aiter(*a, **kw):
                for c in chunks:
                    yield c

            mock_stream = MagicMock()
            mock_stream.__aiter__ = fake_aiter
            provider._client.chat.completions.create = AsyncMock(return_value=mock_stream)

            tools = [{"name": "search", "description": "s", "input_schema": {}}]
            await provider.stream_chat("m", 100, 0.0, "", [], tools)

            # Check tools kwarg was passed
            call_kwargs = provider._client.chat.completions.create.call_args[1]
            self.assertIn("tools", call_kwargs)

        asyncio.run(go())


class OpenAIProviderCreateMessageTests(unittest.TestCase):
    def _make_provider(self) -> OpenAIProvider:
        with patch("openai.AsyncOpenAI"):
            return OpenAIProvider(api_key="test")

    def test_basic_compaction(self) -> None:
        async def go():
            provider = self._make_provider()

            resp = MagicMock()
            choice = MagicMock()
            choice.message.content = "summary text"
            resp.choices = [choice]
            usage = MagicMock()
            usage.prompt_tokens = 50
            usage.completion_tokens = 20
            usage.prompt_tokens_details = None
            resp.usage = usage
            provider._client.chat.completions.create = AsyncMock(return_value=resp)

            text, result_usage = await provider.create_message(
                model="gpt-4", max_tokens=500, temperature=0.0,
                messages=[{"role": "user", "content": "summarize"}],
            )

            self.assertEqual("summary text", text)
            self.assertEqual(50, result_usage.input_tokens)

        asyncio.run(go())

    def test_null_content(self) -> None:
        async def go():
            provider = self._make_provider()
            resp = MagicMock()
            choice = MagicMock()
            choice.message.content = None
            resp.choices = [choice]
            resp.usage = None
            provider._client.chat.completions.create = AsyncMock(return_value=resp)

            text, _ = await provider.create_message("m", 100, 0.0, [])
            self.assertEqual("", text)

        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
