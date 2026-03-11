"""Tests for ToolResultFormatter."""

from __future__ import annotations

import json
import unittest

from micro_x_agent_loop.tool_result_formatter import ToolResultFormatter


class FormatNoStructuredTests(unittest.TestCase):
    """When structured=None, the text fallback is returned unchanged."""

    def test_returns_text_when_no_structured(self) -> None:
        fmt = ToolResultFormatter()
        result = fmt.format("any_tool", "plain text", None)
        self.assertEqual("plain text", result)


class FormatJsonTests(unittest.TestCase):
    """Default strategy (json) serialises structured to indented JSON."""

    def test_default_json_format(self) -> None:
        fmt = ToolResultFormatter()
        structured = {"key": "value", "num": 42}
        result = fmt.format("my_tool", "", structured)
        parsed = json.loads(result)
        self.assertEqual("value", parsed["key"])
        self.assertEqual(42, parsed["num"])

    def test_explicit_json_strategy(self) -> None:
        fmt = ToolResultFormatter(
            tool_formatting={"my_tool": {"format": "json"}},
        )
        result = fmt.format("my_tool", "", {"x": 1})
        self.assertIn('"x"', result)

    def test_non_serializable_falls_back_to_str(self) -> None:
        fmt = ToolResultFormatter()
        structured = {"obj": object()}
        # Should not raise — default=str handles non-serializable types
        result = fmt.format("t", "", structured)
        self.assertIsInstance(result, str)


class FormatTextTests(unittest.TestCase):
    """Strategy 'text': returns a named field or single string value."""

    def test_named_field_extracted(self) -> None:
        fmt = ToolResultFormatter(
            tool_formatting={"my_tool": {"format": "text", "field": "content"}},
        )
        result = fmt.format("my_tool", "", {"content": "hello world", "other": 123})
        self.assertEqual("hello world", result)

    def test_named_field_non_string_converted(self) -> None:
        fmt = ToolResultFormatter(
            tool_formatting={"t": {"format": "text", "field": "count"}},
        )
        result = fmt.format("t", "", {"count": 42})
        self.assertEqual("42", result)

    def test_missing_field_falls_back_to_single_string(self) -> None:
        fmt = ToolResultFormatter(
            tool_formatting={"t": {"format": "text", "field": "missing"}},
        )
        result = fmt.format("t", "", {"value": "the only string"})
        self.assertEqual("the only string", result)

    def test_no_field_single_string_heuristic(self) -> None:
        fmt = ToolResultFormatter(
            tool_formatting={"t": {"format": "text"}},
        )
        result = fmt.format("t", "", {"msg": "just this"})
        self.assertEqual("just this", result)

    def test_multiple_strings_falls_back_to_json(self) -> None:
        fmt = ToolResultFormatter(
            tool_formatting={"t": {"format": "text"}},
        )
        result = fmt.format("t", "", {"a": "one", "b": "two"})
        # Should be valid JSON since there are multiple strings and no single winner
        parsed = json.loads(result)
        self.assertEqual("one", parsed["a"])


class FormatKeyValueTests(unittest.TestCase):
    def test_simple_key_value(self) -> None:
        fmt = ToolResultFormatter(
            tool_formatting={"t": {"format": "key_value"}},
        )
        result = fmt.format("t", "", {"name": "Alice", "age": 30})
        self.assertIn("name: Alice", result)
        self.assertIn("age: 30", result)

    def test_nested_value_json_encoded(self) -> None:
        fmt = ToolResultFormatter(
            tool_formatting={"t": {"format": "key_value"}},
        )
        result = fmt.format("t", "", {"tags": ["a", "b"]})
        self.assertIn("tags:", result)
        self.assertIn('"a"', result)

    def test_dict_value_json_encoded(self) -> None:
        fmt = ToolResultFormatter(
            tool_formatting={"t": {"format": "key_value"}},
        )
        result = fmt.format("t", "", {"meta": {"x": 1}})
        self.assertIn("meta:", result)
        self.assertIn('"x"', result)


class FormatTableTests(unittest.TestCase):
    def test_list_of_dicts(self) -> None:
        fmt = ToolResultFormatter(
            tool_formatting={"t": {"format": "table"}},
        )
        rows = [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]
        result = fmt.format("t", "", rows)  # type: ignore[arg-type]
        self.assertIn("name", result)
        self.assertIn("Alice", result)
        self.assertIn("Bob", result)
        self.assertIn("|", result)

    def test_dict_with_list_value(self) -> None:
        fmt = ToolResultFormatter(
            tool_formatting={"t": {"format": "table"}},
        )
        structured = {"items": [{"id": 1, "label": "x"}]}
        result = fmt.format("t", "", structured)
        self.assertIn("id", result)
        self.assertIn("label", result)

    def test_empty_rows(self) -> None:
        fmt = ToolResultFormatter(
            tool_formatting={"t": {"format": "table"}},
        )
        result = fmt.format("t", "", [])
        self.assertEqual("(empty)", result)

    def test_no_array_falls_back_to_key_value(self) -> None:
        fmt = ToolResultFormatter(
            tool_formatting={"t": {"format": "table"}},
        )
        result = fmt.format("t", "", {"name": "Alice"})
        self.assertIn("name: Alice", result)

    def test_max_rows_truncation(self) -> None:
        fmt = ToolResultFormatter(
            tool_formatting={"t": {"format": "table", "max_rows": 2}},
        )
        rows = [{"id": i} for i in range(5)]
        result = fmt.format("t", "", rows)  # type: ignore[arg-type]
        self.assertIn("Showing 2 of 5", result)

    def test_no_truncation_when_within_limit(self) -> None:
        fmt = ToolResultFormatter(
            tool_formatting={"t": {"format": "table", "max_rows": 10}},
        )
        rows = [{"id": i} for i in range(3)]
        result = fmt.format("t", "", rows)  # type: ignore[arg-type]
        self.assertNotIn("Showing", result)

    def test_column_order_consistent(self) -> None:
        fmt = ToolResultFormatter(
            tool_formatting={"t": {"format": "table"}},
        )
        rows = [{"a": 1, "b": 2}, {"b": 3, "c": 4}]
        result = fmt.format("t", "", rows)  # type: ignore[arg-type]
        # Header should contain all discovered columns
        header_line = result.splitlines()[0]
        self.assertIn("a", header_line)
        self.assertIn("b", header_line)
        self.assertIn("c", header_line)


class DefaultFormatConfigTests(unittest.TestCase):
    def test_default_format_property(self) -> None:
        fmt = ToolResultFormatter(default_format={"format": "key_value"})
        self.assertEqual({"format": "key_value"}, fmt.default_format)

    def test_get_tool_format_returns_none_for_unknown(self) -> None:
        fmt = ToolResultFormatter()
        self.assertIsNone(fmt.get_tool_format("nonexistent"))

    def test_get_tool_format_returns_config(self) -> None:
        config = {"format": "text", "field": "msg"}
        fmt = ToolResultFormatter(tool_formatting={"t": config})
        self.assertEqual(config, fmt.get_tool_format("t"))

    def test_default_format_used_when_no_tool_config(self) -> None:
        fmt = ToolResultFormatter(default_format={"format": "key_value"})
        result = fmt.format("unknown_tool", "", {"x": "hello"})
        self.assertIn("x: hello", result)


if __name__ == "__main__":
    unittest.main()
