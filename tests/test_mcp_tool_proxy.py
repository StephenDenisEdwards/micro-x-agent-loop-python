"""Tests for McpToolProxy."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from micro_x_agent_loop.mcp.mcp_tool_proxy import McpToolProxy


def _make_session(
    *,
    text_parts: list[str] = ("output text",),
    is_error: bool = False,
    structured: dict | None = None,
) -> MagicMock:
    from mcp.types import TextContent

    content = [TextContent(type="text", text=t) for t in text_parts]
    call_result = MagicMock()
    call_result.isError = is_error
    call_result.content = content
    if structured is not None:
        call_result.structuredContent = structured
    else:
        # No structuredContent attribute
        del call_result.structuredContent
    session = MagicMock()
    session.call_tool = AsyncMock(return_value=call_result)
    return session


class McpToolProxyPropertiesTests(unittest.TestCase):
    def _make_proxy(self, **kwargs) -> McpToolProxy:
        defaults = {
            "server_name": "myserver",
            "tool_name": "mytool",
            "tool_description": "Does something",
            "tool_input_schema": {"type": "object"},
            "session": MagicMock(),
        }
        defaults.update(kwargs)
        return McpToolProxy(**defaults)

    def test_name_combines_server_and_tool(self) -> None:
        p = self._make_proxy()
        self.assertEqual("myserver__mytool", p.name)

    def test_description(self) -> None:
        p = self._make_proxy()
        self.assertEqual("Does something", p.description)

    def test_description_none_becomes_empty(self) -> None:
        p = self._make_proxy(tool_description=None)
        self.assertEqual("", p.description)

    def test_input_schema(self) -> None:
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        p = self._make_proxy(tool_input_schema=schema)
        self.assertEqual(schema, p.input_schema)

    def test_is_mutating_default_false(self) -> None:
        p = self._make_proxy()
        self.assertFalse(p.is_mutating)

    def test_is_mutating_true(self) -> None:
        p = self._make_proxy(is_mutating=True)
        self.assertTrue(p.is_mutating)

    def test_output_schema_none_by_default(self) -> None:
        p = self._make_proxy()
        self.assertIsNone(p.output_schema)

    def test_output_schema_set(self) -> None:
        schema = {"type": "object"}
        p = self._make_proxy(output_schema=schema)
        self.assertEqual(schema, p.output_schema)

    def test_predict_touched_paths_returns_empty(self) -> None:
        p = self._make_proxy()
        self.assertEqual([], p.predict_touched_paths({}))


class McpToolProxyExecuteTests(unittest.TestCase):
    def _make_proxy(self, session: MagicMock, **kwargs) -> McpToolProxy:
        return McpToolProxy(
            server_name="srv",
            tool_name="tool",
            tool_description="desc",
            tool_input_schema={"type": "object"},
            session=session,
            **kwargs,
        )

    def test_execute_success(self) -> None:
        session = _make_session(text_parts=["result output"])
        proxy = self._make_proxy(session)
        result = asyncio.run(proxy.execute({"arg": "value"}))
        self.assertEqual("result output", result.text)
        self.assertFalse(result.is_error)

    def test_execute_multiple_text_parts(self) -> None:
        session = _make_session(text_parts=["part1", "part2"])
        proxy = self._make_proxy(session)
        result = asyncio.run(proxy.execute({}))
        self.assertEqual("part1\npart2", result.text)

    def test_execute_no_text_parts(self) -> None:
        call_result = MagicMock()
        call_result.isError = False
        call_result.content = []
        del call_result.structuredContent
        session = MagicMock()
        session.call_tool = AsyncMock(return_value=call_result)
        proxy = self._make_proxy(session)
        result = asyncio.run(proxy.execute({}))
        self.assertEqual("(no output)", result.text)

    def test_execute_error_result(self) -> None:
        session = _make_session(text_parts=["error details"], is_error=True)
        proxy = self._make_proxy(session)
        result = asyncio.run(proxy.execute({}))
        self.assertEqual("error details", result.text)
        self.assertTrue(result.is_error)

    def test_execute_with_structured_content(self) -> None:
        from mcp.types import TextContent

        structured = {"key": "value", "count": 3}
        call_result = MagicMock()
        call_result.isError = False
        call_result.content = [TextContent(type="text", text="text")]
        call_result.structuredContent = structured
        session = MagicMock()
        session.call_tool = AsyncMock(return_value=call_result)
        proxy = self._make_proxy(session)
        result = asyncio.run(proxy.execute({}))
        self.assertIsNotNone(result.structured)
        self.assertEqual("value", result.structured["key"])

    def test_execute_passes_tool_input(self) -> None:
        session = _make_session()
        proxy = self._make_proxy(session)
        input_data = {"path": "/tmp/file.txt", "content": "hello"}
        asyncio.run(proxy.execute(input_data))
        session.call_tool.assert_called_once_with("tool", arguments=input_data)

    def test_execute_no_structured_content_attr(self) -> None:
        """Handles the case where structuredContent attribute is absent."""
        from mcp.types import TextContent

        call_result = MagicMock(spec=["isError", "content"])
        call_result.isError = False
        call_result.content = [TextContent(type="text", text="ok")]
        session = MagicMock()
        session.call_tool = AsyncMock(return_value=call_result)
        proxy = self._make_proxy(session)
        result = asyncio.run(proxy.execute({}))
        self.assertEqual("ok", result.text)
        self.assertIsNone(result.structured)


if __name__ == "__main__":
    unittest.main()
