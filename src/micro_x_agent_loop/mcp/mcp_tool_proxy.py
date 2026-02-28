import json
from typing import Any

from loguru import logger
from mcp import ClientSession
from mcp.types import TextContent

from micro_x_agent_loop.tool import ToolResult


class McpToolProxy:
    """Adapter that wraps an MCP tool definition + session into a Tool Protocol object."""

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        tool_description: str | None,
        tool_input_schema: dict[str, Any],
        session: ClientSession,
        *,
        is_mutating: bool = False,
        output_schema: dict[str, Any] | None = None,
    ):
        self._server_name = server_name
        self._tool_name = tool_name
        self._description = tool_description or ""
        self._input_schema = tool_input_schema
        self._session = session
        self._is_mutating = is_mutating
        self._output_schema = output_schema

    @property
    def name(self) -> str:
        return f"{self._server_name}__{self._tool_name}"

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    @property
    def is_mutating(self) -> bool:
        return self._is_mutating

    @property
    def output_schema(self) -> dict[str, Any] | None:
        return self._output_schema

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]:
        return []

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult:
        logger.debug("MCP tool call: {name} | input: {input}", name=self.name, input=json.dumps(tool_input, default=str))
        result = await self._session.call_tool(self._tool_name, arguments=tool_input)
        logger.debug(
            "MCP raw response: {name} | isError={err} | blocks={count} | types={types}",
            name=self.name,
            err=result.isError,
            count=len(result.content),
            types=[type(b).__name__ for b in result.content],
        )

        text_parts = [block.text for block in result.content if isinstance(block, TextContent)]
        output = "\n".join(text_parts) if text_parts else "(no output)"

        # Extract structuredContent if present
        structured: dict[str, Any] | None = None
        if hasattr(result, "structuredContent") and result.structuredContent is not None:
            structured = dict(result.structuredContent)

        if result.isError:
            logger.warning("MCP tool error: {name} | result: {output}", name=self.name, output=output[:500])
            return ToolResult(text=output, structured=structured, is_error=True)

        logger.debug("MCP tool result: {name} | chars={chars} | result: {output}", name=self.name, chars=len(output), output=output[:500])
        return ToolResult(text=output, structured=structured)
