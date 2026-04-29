"""Tests for Gemini provider format conversion functions."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

# Mock google.genai.types before importing the module
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


class BuildToolUseIdMapTests(unittest.TestCase):
    def test_extracts_tool_use_ids(self) -> None:
        from micro_x_agent_loop.providers.gemini_provider import _build_tool_use_id_map

        messages = [
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me search."},
                    {"type": "tool_use", "id": "tu_1", "name": "web_search", "input": {}},
                ],
            },
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": "results"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "tu_2", "name": "read_file", "input": {}},
                ],
            },
        ]
        id_map = _build_tool_use_id_map(messages)
        self.assertEqual({"tu_1": "web_search", "tu_2": "read_file"}, id_map)

    def test_empty_messages(self) -> None:
        from micro_x_agent_loop.providers.gemini_provider import _build_tool_use_id_map

        self.assertEqual({}, _build_tool_use_id_map([]))

    def test_no_assistant_messages(self) -> None:
        from micro_x_agent_loop.providers.gemini_provider import _build_tool_use_id_map

        messages = [{"role": "user", "content": "hello"}]
        self.assertEqual({}, _build_tool_use_id_map(messages))

    def test_string_content_skipped(self) -> None:
        from micro_x_agent_loop.providers.gemini_provider import _build_tool_use_id_map

        messages = [{"role": "assistant", "content": "just text"}]
        self.assertEqual({}, _build_tool_use_id_map(messages))


class ToGeminiContentsTests(unittest.TestCase):
    @patch.dict("sys.modules", {"google.genai": MagicMock(), "google.genai.types": _mock_types, "google": MagicMock()})
    def test_user_string_content(self) -> None:
        # Re-import with mocked google.genai
        import importlib

        from micro_x_agent_loop.providers import gemini_provider

        importlib.reload(gemini_provider)

        with patch.object(gemini_provider, "_build_tool_use_id_map", return_value={}):
            with patch("google.genai.types", _mock_types):
                messages = [{"role": "user", "content": "hello"}]
                result = gemini_provider._to_gemini_contents(messages)
                self.assertEqual(1, len(result))

    @patch.dict("sys.modules", {"google.genai": MagicMock(), "google.genai.types": _mock_types, "google": MagicMock()})
    def test_assistant_text_and_tool_use(self) -> None:
        import importlib

        from micro_x_agent_loop.providers import gemini_provider

        importlib.reload(gemini_provider)

        with patch.object(gemini_provider, "_build_tool_use_id_map", return_value={}):
            with patch("google.genai.types", _mock_types):
                messages = [
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "Searching..."},
                            {"type": "tool_use", "id": "t1", "name": "search", "input": {"q": "test"}},
                        ],
                    }
                ]
                result = gemini_provider._to_gemini_contents(messages)
                self.assertEqual(1, len(result))


class ToGeminiToolsTests(unittest.TestCase):
    @patch.dict("sys.modules", {"google.genai": MagicMock(), "google.genai.types": _mock_types, "google": MagicMock()})
    def test_empty_tools(self) -> None:
        import importlib

        from micro_x_agent_loop.providers import gemini_provider

        importlib.reload(gemini_provider)

        with patch("google.genai.types", _mock_types):
            result = gemini_provider._to_gemini_tools([])
            self.assertIsNone(result)

    @patch.dict("sys.modules", {"google.genai": MagicMock(), "google.genai.types": _mock_types, "google": MagicMock()})
    def test_converts_tools(self) -> None:
        import importlib

        from micro_x_agent_loop.providers import gemini_provider

        importlib.reload(gemini_provider)

        with patch("google.genai.types", _mock_types):
            tools = [
                {"name": "search", "description": "Search web", "input_schema": {"type": "object"}},
                {"name": "read", "description": "Read file", "input_schema": {"type": "object"}},
            ]
            result = gemini_provider._to_gemini_tools(tools)
            self.assertIsNotNone(result)
            self.assertEqual(1, len(result))  # Wrapped in single Tool object


if __name__ == "__main__":
    unittest.main()
