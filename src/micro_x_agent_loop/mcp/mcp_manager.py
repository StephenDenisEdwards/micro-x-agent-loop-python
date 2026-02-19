import asyncio
import os
from typing import Any

from loguru import logger
from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from micro_x_agent_loop.mcp.mcp_tool_proxy import McpToolProxy
from micro_x_agent_loop.tool import Tool

_SHUTDOWN_TIMEOUT = 5.0


class _ServerConnection:
    """Holds a running server's session and shutdown control."""

    def __init__(self, name: str):
        self.name = name
        self.session: ClientSession | None = None
        self.tools: list[Tool] = []
        self._ready = asyncio.Event()
        self._shutdown = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._error: Exception | None = None

    async def wait_ready(self) -> None:
        await self._ready.wait()
        if self._error:
            raise self._error

    async def _run_stdio(self, config: dict[str, Any]) -> None:
        # Preserve parent process environment (including .env-loaded secrets)
        # and allow per-server overrides from config.
        merged_env = dict(os.environ)
        merged_env.update(config.get("env") or {})
        async with stdio_client(StdioServerParameters(
            command=config["command"],
            args=config.get("args", []),
            env=merged_env,
        )) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                self.session = session
                tools_result = await session.list_tools()
                self.tools = [
                    McpToolProxy(
                        server_name=self.name,
                        tool_name=tool.name,
                        tool_description=tool.description,
                        tool_input_schema=tool.inputSchema,
                        session=session,
                    )
                    for tool in tools_result.tools
                ]
                self._ready.set()
                await self._shutdown.wait()

    async def _run_http(self, config: dict[str, Any]) -> None:
        async with streamable_http_client(config["url"]) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                self.session = session
                tools_result = await session.list_tools()
                self.tools = [
                    McpToolProxy(
                        server_name=self.name,
                        tool_name=tool.name,
                        tool_description=tool.description,
                        tool_input_schema=tool.inputSchema,
                        session=session,
                    )
                    for tool in tools_result.tools
                ]
                self._ready.set()
                await self._shutdown.wait()

    async def start(self, config: dict[str, Any]) -> None:
        transport = config.get("transport", "stdio")

        async def _run():
            try:
                if transport == "stdio":
                    await self._run_stdio(config)
                elif transport == "http":
                    await self._run_http(config)
                else:
                    raise ValueError(f"Unknown transport '{transport}'")
            except Exception as ex:
                self._error = ex
                self._ready.set()

        self._task = asyncio.create_task(_run())

    async def stop(self) -> None:
        if self._task is None or self._task.done():
            return
        # Signal shutdown and cancel — both are needed because stdio_client's
        # internal anyio task group may not respond to asyncio cancellation alone.
        self._shutdown.set()
        self._task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout=_SHUTDOWN_TIMEOUT)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass


class McpManager:
    """Manages connections to all configured MCP servers."""

    def __init__(self, server_configs: dict[str, dict[str, Any]]):
        self._server_configs = server_configs
        self._connections: list[_ServerConnection] = []

    async def connect_all(self) -> list[Tool]:
        """Connect to all configured MCP servers and return discovered tools."""
        all_tools: list[Tool] = []

        for server_name, config in self._server_configs.items():
            conn = _ServerConnection(server_name)
            self._connections.append(conn)

            try:
                await conn.start(config)
                await conn.wait_ready()
                all_tools.extend(conn.tools)
                logger.info(f"MCP server '{server_name}': {len(conn.tools)} tool(s) discovered")
            except Exception as ex:
                logger.error(f"Failed to connect to MCP server '{server_name}': {ex}")

        return all_tools

    async def close(self) -> None:
        """Shut down all MCP servers."""
        for conn in self._connections:
            logger.debug(f"Shutting down MCP server '{conn.name}'...")
            try:
                await conn.stop()
                logger.debug(f"MCP server '{conn.name}' shut down")
            except Exception as ex:
                logger.warning(f"MCP server '{conn.name}' shutdown error: {ex}")
        self._connections.clear()
