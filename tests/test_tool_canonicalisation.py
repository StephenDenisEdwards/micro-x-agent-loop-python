"""Tests for canonical tool serialisation — cache stability."""

from __future__ import annotations

import json
import unittest

from micro_x_agent_loop.tool import _sort_schema, canonicalise_tools
from tests.fakes import FakeTool


class TestSortSchema(unittest.TestCase):
    def test_sorts_dict_keys(self) -> None:
        self.assertEqual({"a": 1, "b": 2, "z": 3}, _sort_schema({"z": 3, "a": 1, "b": 2}))

    def test_nested_dicts(self) -> None:
        result = _sort_schema({"z": {"b": 2, "a": 1}, "a": 0})
        self.assertEqual({"a": 0, "z": {"a": 1, "b": 2}}, result)

    def test_list_preserved(self) -> None:
        result = _sort_schema([{"b": 1, "a": 2}, {"d": 3, "c": 4}])
        self.assertEqual([{"a": 2, "b": 1}, {"c": 4, "d": 3}], result)

    def test_primitives_unchanged(self) -> None:
        self.assertEqual(42, _sort_schema(42))
        self.assertEqual("hello", _sort_schema("hello"))
        self.assertTrue(_sort_schema(True))
        self.assertIsNone(_sort_schema(None))

    def test_complex_schema(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "Content"},
            },
            "required": ["path", "content"],
        }
        result = _sort_schema(schema)
        keys = list(result.keys())
        self.assertEqual(sorted(keys), keys)
        prop_keys = list(result["properties"].keys())
        self.assertEqual(sorted(prop_keys), prop_keys)


class TestCanonicaliseTools(unittest.TestCase):
    def test_sorts_by_name(self) -> None:
        tools = [
            FakeTool(name="z_tool", description="last"),
            FakeTool(name="a_tool", description="first"),
            FakeTool(name="m_tool", description="middle"),
        ]
        result = canonicalise_tools(tools)
        names = [t["name"] for t in result]
        self.assertEqual(["a_tool", "m_tool", "z_tool"], names)

    def test_order_independent(self) -> None:
        tools_a = [
            FakeTool(name="beta", description="b"),
            FakeTool(name="alpha", description="a"),
        ]
        tools_b = [
            FakeTool(name="alpha", description="a"),
            FakeTool(name="beta", description="b"),
        ]
        self.assertEqual(canonicalise_tools(tools_a), canonicalise_tools(tools_b))

    def test_schema_keys_sorted(self) -> None:
        tools = [
            FakeTool(
                name="tool",
                description="d",
                input_schema={
                    "type": "object",
                    "properties": {"z": {"type": "string"}, "a": {"type": "number"}},
                    "required": ["z", "a"],
                },
            ),
        ]
        result = canonicalise_tools(tools)
        schema = result[0]["input_schema"]
        self.assertEqual(sorted(schema.keys()), list(schema.keys()))
        self.assertEqual(sorted(schema["properties"].keys()), list(schema["properties"].keys()))

    def test_byte_stability(self) -> None:
        """Serialised JSON is byte-identical across multiple calls."""
        tools = [
            FakeTool(name="z", description="z", input_schema={"b": 1, "a": 2}),
            FakeTool(name="a", description="a", input_schema={"d": 3, "c": 4}),
        ]
        json1 = json.dumps(canonicalise_tools(tools), separators=(",", ":"))
        json2 = json.dumps(canonicalise_tools(tools), separators=(",", ":"))
        self.assertEqual(json1, json2)

    def test_empty_tools(self) -> None:
        self.assertEqual([], canonicalise_tools([]))

    def test_does_not_mutate_original(self) -> None:
        tools = [
            FakeTool(name="b", description="b"),
            FakeTool(name="a", description="a"),
        ]
        original_names = [t.name for t in tools]
        canonicalise_tools(tools)
        self.assertEqual(original_names, [t.name for t in tools])


class TestProviderUsesCanonicalisation(unittest.TestCase):
    """Verify that both providers produce canonically-ordered output."""

    def _convert_via_provider(self, provider_cls: type, tools: list[FakeTool]) -> list[dict]:
        """Instantiate a provider and call convert_tools."""
        # Both providers require an api_key; we pass a dummy one
        if provider_cls.__name__ == "AnthropicProvider":
            p = provider_cls("dummy-key", prompt_caching_enabled=False)
        else:
            p = provider_cls("dummy-key")
        return p.convert_tools(tools)

    def test_anthropic_provider_canonical(self) -> None:
        from micro_x_agent_loop.providers.anthropic_provider import AnthropicProvider

        tools = [FakeTool(name="z", description="z"), FakeTool(name="a", description="a")]
        result = self._convert_via_provider(AnthropicProvider, tools)
        names = [t["name"] for t in result]
        self.assertEqual(["a", "z"], names)

    def test_openai_provider_canonical(self) -> None:
        from micro_x_agent_loop.providers.openai_provider import OpenAIProvider

        tools = [FakeTool(name="z", description="z"), FakeTool(name="a", description="a")]
        result = self._convert_via_provider(OpenAIProvider, tools)
        names = [t["name"] for t in result]
        self.assertEqual(["a", "z"], names)


if __name__ == "__main__":
    unittest.main()
