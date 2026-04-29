import asyncio
import os
from typing import Any

from loguru import logger
from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import LoggingMessageNotificationParams

from micro_x_agent_loop.llm_client import print_through_spinner
from micro_x_agent_loop.mcp.mcp_tool_proxy import McpToolProxy
from micro_x_agent_loop.tool import Tool

_SHUTDOWN_TIMEOUT = 5.0


# ---------------------------------------------------------------------------
# MCP notification routing — routes log notifications to active channels
# ---------------------------------------------------------------------------

_notification_channels: set[Any] = set()


def add_notification_channel(channel: Any) -> None:
    """Register a channel to receive MCP logging notifications."""
    _notification_channels.add(channel)


def remove_notification_channel(channel: Any) -> None:
    """Unregister a channel from MCP logging notifications."""
    _notification_channels.discard(channel)


async def _mcp_logging_callback(params: LoggingMessageNotificationParams) -> None:
    """Forward MCP server log notifications to active channels and loguru.

    MCP servers use ctx.info()/ctx.warning()/ctx.error() for user-facing
    progress messages (e.g. codegen status).  These are routed to all
    registered channels, or fall back to terminal output when none are active.
    """
    level = str(params.level).upper()
    source = f"mcp.{params.logger}" if params.logger else "mcp"
    msg = str(params.data) if params.data is not None else ""

    text = f"[{source}] {msg}"
    if _notification_channels:
        for channel in _notification_channels:
            channel.emit_system_message(text)
    else:
        # Fallback: direct terminal output (e.g. during startup before any channel)
        print_through_spinner(text)

    # Also forward to loguru for file/structured logging
    getattr(logger.opt(depth=1), level.lower(), logger.info)(f"[{source}] {msg}")


def _build_proxies(server_name: str, tools_result: Any, session: ClientSession) -> list[Tool]:
    """Build McpToolProxy instances from discovered MCP tools."""
    proxies: list[Tool] = []
    for tool in tools_result.tools:
        is_mutating = bool(getattr(tool.annotations, "destructiveHint", False)) if tool.annotations else False
        output_schema: dict[str, Any] | None = None
        if hasattr(tool, "outputSchema") and tool.outputSchema is not None:
            output_schema = dict(tool.outputSchema)
        proxies.append(
            McpToolProxy(
                server_name=server_name,
                tool_name=tool.name,
                tool_description=tool.description,
                tool_input_schema=tool.inputSchema,
                session=session,
                is_mutating=is_mutating,
                output_schema=output_schema,
            )
        )
    return proxies


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
        params = StdioServerParameters(
            command=config["command"],
            args=config.get("args", []),
            env=merged_env,
        )
        if config.get("cwd"):
            params.cwd = config["cwd"]
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(
                read_stream,
                write_stream,
                logging_callback=_mcp_logging_callback,
            ) as session:
                await session.initialize()
                self.session = session
                tools_result = await session.list_tools()
                self.tools = _build_proxies(self.name, tools_result, session)
                self._ready.set()
                await self._shutdown.wait()

    async def _run_http(self, config: dict[str, Any]) -> None:
        async with streamable_http_client(config["url"]) as (read_stream, write_stream, _):
            async with ClientSession(
                read_stream,
                write_stream,
                logging_callback=_mcp_logging_callback,
            ) as session:
                await session.initialize()
                self.session = session
                tools_result = await session.list_tools()
                self.tools = _build_proxies(self.name, tools_result, session)
                self._ready.set()
                await self._shutdown.wait()

    async def start(self, config: dict[str, Any]) -> None:
        transport = config.get("transport", "stdio")

        async def _run() -> None:
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
        except (TimeoutError, asyncio.CancelledError):
            pass


class McpManager:
    """Manages connections to all configured MCP servers."""

    def __init__(self, server_configs: dict[str, dict[str, Any]]):
        self._server_configs = server_configs
        self._connections: list[_ServerConnection] = []

    async def connect_all(self) -> list[Tool]:
        """Connect to all configured MCP servers in parallel and return discovered tools."""
        connections: list[_ServerConnection] = []
        for server_name, config in self._server_configs.items():
            conn = _ServerConnection(server_name)
            connections.append(conn)
            self._connections.append(conn)
            await conn.start(config)

        # Wait for all servers to become ready in parallel.
        all_tools: list[Tool] = []
        for conn in connections:
            try:
                await conn.wait_ready()
                all_tools.extend(conn.tools)
                logger.info(f"MCP server '{conn.name}': {len(conn.tools)} tool(s) discovered")
            except Exception as ex:
                logger.error(f"Failed to connect to MCP server '{conn.name}': {ex}")

        return all_tools

    async def connect_on_demand(self, server_name: str, config: dict[str, Any]) -> list[Tool]:
        """Connect to a single MCP server on demand and return its tools.

        Used for generated MCP servers from the manifest. The connection
        is kept alive and cleaned up on close().
        """
        conn = _ServerConnection(server_name)
        self._connections.append(conn)
        await conn.start(config)
        await conn.wait_ready()
        logger.info(f"On-demand MCP server '{server_name}': {len(conn.tools)} tool(s)")
        return conn.tools

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
