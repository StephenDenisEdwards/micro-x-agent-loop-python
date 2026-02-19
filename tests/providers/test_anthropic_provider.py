import asyncio
import unittest
from types import SimpleNamespace
from typing import Any

from micro_x_agent_loop.providers.anthropic_provider import AnthropicProvider


class _FakeStreamContext:
    def __init__(self, events: list[object], final_message: object):
        self._events = events
        self._final_message = final_message

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def __aiter__(self):
        self._iter = iter(self._events)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration

    async def get_final_message(self):
        return self._final_message


class _FakeMessages:
    def __init__(self, stream_ctx=None, create_response=None):
        self._stream_ctx = stream_ctx
        self._create_response = create_response

    def stream(self, **kwargs):
        return self._stream_ctx

    async def create(self, **kwargs):
        return self._create_response


class _FakeClient:
    def __init__(self, stream_ctx=None, create_response=None):
        self.messages = _FakeMessages(stream_ctx, create_response)


class _FakeTool:
    def __init__(self, name: str, description: str, input_schema: dict):
        self._name = name
        self._description = description
        self._input_schema = input_schema

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    @property
    def is_mutating(self) -> bool:
        return False

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]:
        return []

    async def execute(self, tool_input: dict[str, Any]) -> str:
        return "ok"


class AnthropicProviderTests(unittest.TestCase):
    def _make_provider(self, stream_ctx=None, create_response=None) -> AnthropicProvider:
        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider._client = _FakeClient(stream_ctx, create_response)
        return provider

    def test_convert_tools(self) -> None:
        provider = self._make_provider()
        tools = [
            _FakeTool("read_file", "Read a file", {"type": "object", "properties": {"path": {"type": "string"}}}),
        ]
        result = provider.convert_tools(tools)
        self.assertEqual(1, len(result))
        self.assertEqual("read_file", result[0]["name"])
        self.assertEqual("Read a file", result[0]["description"])
        self.assertIn("properties", result[0]["input_schema"])

    def test_stream_chat_text_and_tool_use(self) -> None:
        events = [
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="text_delta", text="Hello"),
            )
        ]
        final_message = SimpleNamespace(
            stop_reason="tool_use",
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            content=[
                SimpleNamespace(type="text", text="Hello"),
                SimpleNamespace(type="tool_use", id="t1", name="read_file", input={"path": "x"}),
            ],
        )
        provider = self._make_provider(stream_ctx=_FakeStreamContext(events, final_message))

        message, tool_use_blocks, stop_reason = asyncio.run(
            provider.stream_chat("m", 100, 0.5, "sys", [{"role": "user", "content": "hi"}], [])
        )

        self.assertEqual("assistant", message["role"])
        self.assertEqual("tool_use", stop_reason)
        self.assertEqual(1, len(tool_use_blocks))
        self.assertEqual("read_file", tool_use_blocks[0]["name"])
        self.assertEqual({"path": "x"}, tool_use_blocks[0]["input"])

    def test_stream_chat_text_only(self) -> None:
        events: list[object] = []
        final_message = SimpleNamespace(
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=3, output_tokens=2),
            content=[SimpleNamespace(type="text", text="Done")],
        )
        provider = self._make_provider(stream_ctx=_FakeStreamContext(events, final_message))

        message, tool_use_blocks, stop_reason = asyncio.run(
            provider.stream_chat("m", 100, 0.1, "sys", [{"role": "user", "content": "hi"}], [])
        )

        self.assertEqual("end_turn", stop_reason)
        self.assertEqual([], tool_use_blocks)
        self.assertEqual("Done", message["content"][0]["text"])

    def test_create_message(self) -> None:
        create_response = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=5, output_tokens=3),
            content=[SimpleNamespace(text="summary result")],
        )
        provider = self._make_provider(create_response=create_response)

        result = asyncio.run(
            provider.create_message("m", 4096, 0, [{"role": "user", "content": "summarize"}])
        )
        self.assertEqual("summary result", result)


if __name__ == "__main__":
    unittest.main()
