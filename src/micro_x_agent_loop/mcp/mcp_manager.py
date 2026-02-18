from contextlib import AsyncExitStack
from typing import Any

from loguru import logger
from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from micro_x_agent_loop.mcp.mcp_tool_proxy import McpToolProxy
from micro_x_agent_loop.tool import Tool


class McpManager:
    """Manages connections to all configured MCP servers."""

    def __init__(self, server_configs: dict[str, dict[str, Any]]):
        self._server_configs = server_configs
        self._exit_stack = AsyncExitStack()

    async def connect_all(self) -> list[Tool]:
        """Connect to all configured MCP servers and return discovered tools."""
        all_tools: list[Tool] = []
        await self._exit_stack.__aenter__()

        for server_name, config in self._server_configs.items():
            try:
                tools = await self._connect_server(server_name, config)
                all_tools.extend(tools)
                logger.info(f"MCP server '{server_name}': {len(tools)} tool(s) discovered")
            except Exception as ex:
                logger.error(f"Failed to connect to MCP server '{server_name}': {ex}")

        return all_tools

    async def _connect_server(self, server_name: str, config: dict[str, Any]) -> list[Tool]:
        transport = config.get("transport", "stdio")

        if transport == "stdio":
            read_stream, write_stream = await self._exit_stack.enter_async_context(
                stdio_client(StdioServerParameters(
                    command=config["command"],
                    args=config.get("args", []),
                    env=config.get("env"),
                ))
            )
        elif transport == "http":
            read_stream, write_stream, _ = await self._exit_stack.enter_async_context(
                streamable_http_client(config["url"])
            )
        else:
            raise ValueError(f"Unknown transport '{transport}' for MCP server '{server_name}'")

        session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()

        tools_result = await session.list_tools()

        return [
            McpToolProxy(
                server_name=server_name,
                tool_name=tool.name,
                tool_description=tool.description,
                tool_input_schema=tool.inputSchema,
                session=session,
            )
            for tool in tools_result.tools
        ]

    async def close(self) -> None:
        """Shut down all MCP server connections."""
        await self._exit_stack.aclose()
