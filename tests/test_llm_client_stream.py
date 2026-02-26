import asyncio
import unittest
from types import SimpleNamespace

from micro_x_agent_loop.providers.anthropic_provider import AnthropicProvider
from micro_x_agent_loop.usage import UsageResult
from tests.fakes import FakeAnthropicClient, FakeStreamContext


class AnthropicProviderStreamTests(unittest.TestCase):
    def _make_provider(self, stream_ctx: FakeStreamContext) -> AnthropicProvider:
        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider._client = FakeAnthropicClient(stream_ctx)
        provider._prompt_caching_enabled = False
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
        provider = self._make_provider(FakeStreamContext(events, final_message))

        message, tool_use_blocks, stop_reason, usage = asyncio.run(
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
        self.assertIsInstance(usage, UsageResult)
        self.assertEqual(10, usage.input_tokens)
        self.assertEqual(5, usage.output_tokens)

    def test_stream_chat_handles_no_text_delta(self) -> None:
        events: list[object] = []
        final_message = SimpleNamespace(
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=3, output_tokens=2),
            content=[SimpleNamespace(type="text", text="Done")],
        )
        provider = self._make_provider(FakeStreamContext(events, final_message))

        message, tool_use_blocks, stop_reason, usage = asyncio.run(
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
        self.assertIsInstance(usage, UsageResult)
        self.assertEqual(3, usage.input_tokens)


if __name__ == "__main__":
    unittest.main()
