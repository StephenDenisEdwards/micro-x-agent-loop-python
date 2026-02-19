import asyncio
import unittest
from types import SimpleNamespace

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
    def __init__(self, stream_ctx: _FakeStreamContext):
        self._stream_ctx = stream_ctx

    def stream(self, **kwargs):
        return self._stream_ctx


class _FakeClient:
    def __init__(self, stream_ctx: _FakeStreamContext):
        self.messages = _FakeMessages(stream_ctx)


class AnthropicProviderStreamTests(unittest.TestCase):
    def _make_provider(self, stream_ctx: _FakeStreamContext) -> AnthropicProvider:
        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider._client = _FakeClient(stream_ctx)
        return provider

    def test_stream_chat_returns_text_and_tool_use_blocks(self) -> None:
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
        provider = self._make_provider(_FakeStreamContext(events, final_message))

        message, tool_use_blocks, stop_reason = asyncio.run(
            provider.stream_chat(
                model="m",
                max_tokens=100,
                temperature=0.5,
                system_prompt="sys",
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
                line_prefix="assistant> ",
            )
        )

        self.assertEqual("assistant", message["role"])
        self.assertEqual("tool_use", stop_reason)
        self.assertEqual(1, len(tool_use_blocks))
        self.assertEqual("read_file", tool_use_blocks[0]["name"])

    def test_stream_chat_handles_no_text_delta(self) -> None:
        events: list[object] = []
        final_message = SimpleNamespace(
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=3, output_tokens=2),
            content=[SimpleNamespace(type="text", text="Done")],
        )
        provider = self._make_provider(_FakeStreamContext(events, final_message))

        message, tool_use_blocks, stop_reason = asyncio.run(
            provider.stream_chat(
                model="m",
                max_tokens=100,
                temperature=0.1,
                system_prompt="sys",
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
                line_prefix="assistant> ",
            )
        )

        self.assertEqual("end_turn", stop_reason)
        self.assertEqual([], tool_use_blocks)
        self.assertEqual("Done", message["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
