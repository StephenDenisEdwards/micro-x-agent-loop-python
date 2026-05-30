import unittest
from typing import Any

from loguru import logger as _loguru_logger

from micro_x_agent_loop.providers.gemini_provider import (
    _collapse_combinators,
    _to_gemini_schema,
)


class _LoguruCapture:
    """Capture loguru warnings into a list for assertions (loguru bypasses stdlib logging)."""

    def __init__(self) -> None:
        self.messages: list[str] = []
        self._sink_id: int | None = None

    def __enter__(self) -> "_LoguruCapture":
        def _sink(message: Any) -> None:
            self.messages.append(message.record["message"])

        self._sink_id = _loguru_logger.add(_sink, level="WARNING")
        return self

    def __exit__(self, *_: Any) -> None:
        if self._sink_id is not None:
            _loguru_logger.remove(self._sink_id)


class ToGeminiSchemaTests(unittest.TestCase):
    def test_non_dict_returns_empty(self) -> None:
        self.assertEqual({}, _to_gemini_schema("nope"))
        self.assertEqual({}, _to_gemini_schema(None))

    def test_passthrough_supported_keys(self) -> None:
        schema = {
            "type": "object",
            "description": "a tool input",
            "properties": {
                "name": {"type": "string", "description": "the name"},
                "count": {"type": "integer"},
            },
            "required": ["name"],
        }
        self.assertEqual(schema, _to_gemini_schema(schema))

    def test_strips_unsupported_top_level_keys(self) -> None:
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "$defs": {"X": {"type": "string"}},
            "additionalProperties": False,
            "title": "Thing",
            "default": {},
            "examples": [{}],
            "type": "object",
            "properties": {"a": {"type": "string"}},
        }
        result = _to_gemini_schema(schema)
        self.assertEqual({"type": "object", "properties": {"a": {"type": "string"}}}, result)

    def test_strips_unsupported_keys_recursively(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "nested": {
                    "type": "object",
                    "additionalProperties": True,
                    "title": "Nested",
                    "properties": {"x": {"type": "number", "default": 1}},
                }
            },
        }
        result = _to_gemini_schema(schema)
        self.assertEqual(
            {
                "type": "object",
                "properties": {
                    "nested": {
                        "type": "object",
                        "properties": {"x": {"type": "number"}},
                    }
                },
            },
            result,
        )

    def test_type_array_with_null_becomes_nullable(self) -> None:
        result = _to_gemini_schema({"type": ["string", "null"], "description": "maybe"})
        self.assertEqual({"type": "string", "description": "maybe", "nullable": True}, result)

    def test_type_array_without_null_picks_first(self) -> None:
        result = _to_gemini_schema({"type": ["string", "integer"]})
        self.assertEqual({"type": "string"}, result)

    def test_anyof_collapses_to_first_concrete_branch(self) -> None:
        schema = {
            "anyOf": [{"type": "string"}, {"type": "integer"}],
            "description": "an id",
        }
        result = _to_gemini_schema(schema)
        self.assertEqual({"type": "string", "description": "an id"}, result)

    def test_anyof_with_null_branch_lifts_to_nullable(self) -> None:
        schema = {"anyOf": [{"type": "string"}, {"type": "null"}]}
        result = _to_gemini_schema(schema)
        self.assertEqual({"type": "string", "nullable": True}, result)

    def test_oneof_and_allof_also_collapse(self) -> None:
        self.assertEqual({"type": "string"}, _to_gemini_schema({"oneOf": [{"type": "string"}]}))
        self.assertEqual({"type": "number"}, _to_gemini_schema({"allOf": [{"type": "number"}]}))

    def test_allowed_format_kept_unknown_dropped(self) -> None:
        kept = _to_gemini_schema({"type": "string", "format": "date-time"})
        self.assertEqual({"type": "string", "format": "date-time"}, kept)
        dropped = _to_gemini_schema({"type": "string", "format": "uri"})
        self.assertEqual({"type": "string"}, dropped)

    def test_enum_preserved(self) -> None:
        schema = {"type": "string", "enum": ["a", "b", "c"]}
        self.assertEqual(schema, _to_gemini_schema(schema))

    def test_array_items_sanitised(self) -> None:
        schema = {
            "type": "array",
            "items": {"type": "object", "title": "Item", "properties": {"v": {"type": "string"}}},
        }
        result = _to_gemini_schema(schema)
        self.assertEqual(
            {"type": "array", "items": {"type": "object", "properties": {"v": {"type": "string"}}}},
            result,
        )

    def test_ref_is_dropped_with_warning(self) -> None:
        with _LoguruCapture() as cap:
            result = _to_gemini_schema({"$ref": "#/$defs/Thing", "type": "object"})
        self.assertEqual({"type": "object"}, result)
        self.assertTrue(any("gemini_schema.unresolved_ref" in m for m in cap.messages))

    def test_empty_schema_stays_empty(self) -> None:
        self.assertEqual({}, _to_gemini_schema({}))

    def test_required_filters_non_strings(self) -> None:
        schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a", 3, None]}
        result = _to_gemini_schema(schema)
        self.assertEqual(["a"], result["required"])


class CollapseCombinatorsTests(unittest.TestCase):
    def test_no_combinator_is_identity(self) -> None:
        schema = {"type": "string", "description": "x"}
        self.assertEqual(schema, _collapse_combinators(schema))

    def test_merges_parent_siblings_onto_branch(self) -> None:
        schema = {"anyOf": [{"type": "string"}], "description": "kept"}
        self.assertEqual({"type": "string", "description": "kept"}, _collapse_combinators(schema))

    def test_all_null_branches_yield_empty_concrete(self) -> None:
        result = _collapse_combinators({"anyOf": [{"type": "null"}]})
        self.assertEqual({"nullable": True}, result)


if __name__ == "__main__":
    unittest.main()
