from typing import Any

from mcp import ClientSession
from mcp.types import TextContent


class McpToolProxy:
    """Adapter that wraps an MCP tool definition + session into a Tool Protocol object."""

    def __init__(self, server_name: str, tool_name: str, tool_description: str | None, tool_input_schema: dict[str, Any], session: ClientSession):
        self._server_name = server_name
        self._tool_name = tool_name
        self._description = tool_description or ""
        self._input_schema = tool_input_schema
        self._session = session

    @property
    def name(self) -> str:
        return f"{self._server_name}__{self._tool_name}"

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    async def execute(self, tool_input: dict[str, Any]) -> str:
        result = await self._session.call_tool(self._tool_name, arguments=tool_input)
        text_parts = [block.text for block in result.content if isinstance(block, TextContent)]
        if result.isError:
            raise RuntimeError("\n".join(text_parts) if text_parts else "MCP tool returned an error with no details")
        return "\n".join(text_parts) if text_parts else "(no output)"
