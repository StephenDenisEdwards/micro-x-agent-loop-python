import asyncio
import unittest
from types import SimpleNamespace

from micro_x_agent_loop.providers.anthropic_provider import AnthropicProvider
from micro_x_agent_loop.usage import UsageResult
from tests.fakes import FakeAnthropicClient, FakeStreamContext, FakeTool


class AnthropicProviderTests(unittest.TestCase):
    def _make_provider(self, stream_ctx=None, create_response=None) -> AnthropicProvider:
        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider._client = FakeAnthropicClient(stream_ctx, create_response)
        provider._prompt_caching_enabled = False
        return provider

    def test_convert_tools(self) -> None:
        provider = self._make_provider()
        tools = [
            FakeTool("read_file", "Read a file", {"type": "object", "properties": {"path": {"type": "string"}}}),
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
        provider = self._make_provider(stream_ctx=FakeStreamContext(events, final_message))

        message, tool_use_blocks, stop_reason, usage = asyncio.run(
            provider.stream_chat("m", 100, 0.5, "sys", [{"role": "user", "content": "hi"}], [])
        )

        self.assertEqual("assistant", message["role"])
        self.assertEqual("tool_use", stop_reason)
        self.assertEqual(1, len(tool_use_blocks))
        self.assertEqual("read_file", tool_use_blocks[0]["name"])
        self.assertEqual({"path": "x"}, tool_use_blocks[0]["input"])
        self.assertIsInstance(usage, UsageResult)
        self.assertEqual(10, usage.input_tokens)
        self.assertEqual(5, usage.output_tokens)
        self.assertEqual("anthropic", usage.provider)

    def test_stream_chat_text_only(self) -> None:
        events: list[object] = []
        final_message = SimpleNamespace(
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=3, output_tokens=2),
            content=[SimpleNamespace(type="text", text="Done")],
        )
        provider = self._make_provider(stream_ctx=FakeStreamContext(events, final_message))

        message, tool_use_blocks, stop_reason, usage = asyncio.run(
            provider.stream_chat("m", 100, 0.1, "sys", [{"role": "user", "content": "hi"}], [])
        )

        self.assertEqual("end_turn", stop_reason)
        self.assertEqual([], tool_use_blocks)
        self.assertEqual("Done", message["content"][0]["text"])
        self.assertIsInstance(usage, UsageResult)
        self.assertEqual(3, usage.input_tokens)
        self.assertEqual(2, usage.output_tokens)
        self.assertEqual("anthropic", usage.provider)

    def test_create_message(self) -> None:
        create_response = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=5, output_tokens=3),
            content=[SimpleNamespace(text="summary result")],
        )
        provider = self._make_provider(create_response=create_response)

        text, usage = asyncio.run(
            provider.create_message("m", 4096, 0, [{"role": "user", "content": "summarize"}])
        )
        self.assertEqual("summary result", text)
        self.assertIsInstance(usage, UsageResult)
        self.assertEqual(5, usage.input_tokens)
        self.assertEqual(3, usage.output_tokens)
        self.assertEqual("anthropic", usage.provider)


if __name__ == "__main__":
    unittest.main()
