import asyncio
import json
import os
from typing import Any

from loguru import logger
from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client as streamable_http_client
from mcp.types import LoggingMessageNotificationParams

from micro_x_agent_loop.llm_client import print_through_spinner
from micro_x_agent_loop.mcp.mcp_tool_proxy import McpToolProxy
from micro_x_agent_loop.tool import Tool

_SHUTDOWN_TIMEOUT = 5.0
_HTTP_READY_TIMEOUT = 30.0  # seconds to wait for an HTTP-transport server to start listening
_HTTP_READY_INTERVAL = 0.2  # seconds between port-readiness probes


def _extract_port(config: dict[str, Any]) -> int:
    """Return the port for an HTTP-transport server.

    Prefers an explicit `port` field, otherwise scans args for `--port <N>`.
    """
    if "port" in config:
        return int(config["port"])
    args = config.get("args") or []
    for i, a in enumerate(args):
        if a == "--port" and i + 1 < len(args):
            return int(args[i + 1])
    raise ValueError(
        "HTTP-transport server config must specify a 'port' field or include "
        "'--port <N>' in args"
    )


def _build_url(config: dict[str, Any], path: str) -> str:
    """Build the URL to connect to. Prefers an explicit `url` field; otherwise
    composes `http://<host>:<port><path>`."""
    if "url" in config:
        return str(config["url"])
    port = _extract_port(config)
    host = config.get("host") or "localhost"
    return f"http://{host}:{port}{path}"


async def _wait_for_port(host: str, port: int, timeout: float) -> None:
    """Poll a TCP port until it accepts connections, or raise on timeout."""
    deadline = asyncio.get_event_loop().time() + timeout
    last_err: Exception | None = None
    while asyncio.get_event_loop().time() < deadline:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=1.0
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return
        except (ConnectionRefusedError, asyncio.TimeoutError, OSError) as ex:
            last_err = ex
            await asyncio.sleep(_HTTP_READY_INTERVAL)
    raise TimeoutError(
        f"Server on {host}:{port} did not start listening within {timeout}s "
        f"(last error: {last_err!r})"
    )


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
        # For HTTP/SSE-transport servers we spawn the subprocess ourselves
        # (mirroring stdio_client's behaviour for the stdio path) and tear
        # it down on stop().
        self._proc: asyncio.subprocess.Process | None = None

    async def wait_ready(self) -> None:
        await self._ready.wait()
        if self._error:
            raise self._error

    async def _run_stdio(
        self,
        config: dict[str, Any],
        resolved_config: dict[str, Any] | None,
    ) -> None:
        # Preserve parent process environment (including .env-loaded secrets)
        # and allow per-server overrides from config.
        merged_env = dict(os.environ)
        merged_env.update(config.get("env") or {})
        # Forward the Agent's resolved config to every spawned MCP server so
        # children (including codegen-generated tasks) execute against the
        # same configuration as the Agent. Set after the per-server merge so
        # the manager's value is the source of truth.
        if resolved_config is not None:
            merged_env["MICRO_X_AGENT_CONFIG_JSON"] = json.dumps(resolved_config)
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

    async def _spawn_subprocess(
        self,
        config: dict[str, Any],
        resolved_config: dict[str, Any] | None,
    ) -> None:
        """Spawn the configured command for an HTTP/SSE-transport server.

        Same env-merge logic as the stdio path so .env-loaded secrets and
        per-server overrides flow through, plus MICRO_X_AGENT_CONFIG_JSON
        forwarding so children see the agent's resolved config.
        """
        if not config.get("command"):
            # Allow attaching to a pre-running external service when no
            # command is configured (just connect to the URL).
            return
        merged_env = dict(os.environ)
        merged_env.update(config.get("env") or {})
        if resolved_config is not None:
            merged_env["MICRO_X_AGENT_CONFIG_JSON"] = json.dumps(resolved_config)
        cwd = config.get("cwd")
        # Discard stdout/stderr — these MCP servers are noisy and we rely
        # on session-level logging callbacks for in-band messages.
        self._proc = await asyncio.create_subprocess_exec(
            config["command"],
            *config.get("args", []),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env=merged_env,
            cwd=cwd,
        )

    async def _run_sse(
        self,
        config: dict[str, Any],
        resolved_config: dict[str, Any] | None,
    ) -> None:
        await self._spawn_subprocess(config, resolved_config)
        port = _extract_port(config)
        host = config.get("host") or "localhost"
        await _wait_for_port(host, port, _HTTP_READY_TIMEOUT)
        url = _build_url(config, "/sse")
        async with sse_client(url) as (read_stream, write_stream):
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

    async def _run_http(
        self,
        config: dict[str, Any],
        resolved_config: dict[str, Any] | None,
    ) -> None:
        await self._spawn_subprocess(config, resolved_config)
        if "url" not in config:
            port = _extract_port(config)
            host = config.get("host") or "localhost"
            await _wait_for_port(host, port, _HTTP_READY_TIMEOUT)
        url = _build_url(config, "")
        async with streamable_http_client(url) as (read_stream, write_stream, _):
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

    async def start(
        self,
        config: dict[str, Any],
        resolved_config: dict[str, Any] | None = None,
    ) -> None:
        transport = config.get("transport", "stdio")

        async def _run() -> None:
            try:
                if transport == "stdio":
                    await self._run_stdio(config, resolved_config)
                elif transport == "sse":
                    await self._run_sse(config, resolved_config)
                elif transport == "http":
                    await self._run_http(config, resolved_config)
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
        # Tear down the spawned subprocess for HTTP/SSE-transport servers.
        # (For stdio, the subprocess is owned by stdio_client's context manager
        # and is already gone by the time we get here.)
        if self._proc is not None and self._proc.returncode is None:
            try:
                self._proc.terminate()
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=_SHUTDOWN_TIMEOUT)
                except asyncio.TimeoutError:
                    self._proc.kill()
                    await self._proc.wait()
            except ProcessLookupError:
                pass


class McpManager:
    """Manages connections to all configured MCP servers."""

    def __init__(
        self,
        server_configs: dict[str, dict[str, Any]],
        resolved_config: dict[str, Any] | None = None,
    ):
        self._server_configs = server_configs
        self._resolved_config = resolved_config
        self._connections: list[_ServerConnection] = []

    async def connect_all(self) -> list[Tool]:
        """Connect to all configured MCP servers in parallel and return discovered tools."""
        connections: list[_ServerConnection] = []
        for server_name, config in self._server_configs.items():
            conn = _ServerConnection(server_name)
            connections.append(conn)
            self._connections.append(conn)
            await conn.start(config, self._resolved_config)

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
        await conn.start(config, self._resolved_config)
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
