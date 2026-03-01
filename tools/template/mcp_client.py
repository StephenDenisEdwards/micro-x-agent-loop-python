"""Lightweight MCP stdio client for connecting to MCP servers and calling tools.

Lifecycle pattern (task-based):
    The stdio_client context manager must stay open for the lifetime of the
    session. We achieve this by running it inside an asyncio.Task, controlled
    by two Events:
    - _ready: set when the session is initialized (or on error)
    - _shutdown: set when we want to tear down

    connect() creates the task and waits for _ready.
    close() signals _shutdown and cancels the task.

Usage:
    client = McpClient("my-server")
    await client.connect(command="node", args=["server.js"])
    tools = await client.list_tools()       # [(name, description), ...]
    result = await client.call_tool("tool_name", {"arg": "value"})
    await client.close()
"""

import asyncio
import os
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_SHUTDOWN_TIMEOUT = 5.0


class McpClient:
    """Connects to an MCP server via stdio and provides tool discovery + calling.

    Uses the task-based lifecycle pattern: the stdio_client context is held
    open inside an asyncio.Task, controlled by Events. This is necessary
    because stdio_client is a context manager that owns the subprocess — if
    it exits, the server dies.
    """

    def __init__(self, name: str):
        self.name = name
        self._session: ClientSession | None = None
        self._ready = asyncio.Event()
        self._shutdown = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._error: Exception | None = None

    async def connect(self, command: str, args: list[str], env: dict[str, str] | None = None) -> None:
        """Start the MCP server process and initialize the session.

        Args:
            command: Executable to run (e.g. "node", "python", "dotnet").
            args: Arguments for the command (e.g. ["server.js"]).
            env: Extra environment variables merged with os.environ.
        """
        merged_env = dict(os.environ)
        if env:
            merged_env.update(env)

        async def _run() -> None:
            try:
                async with stdio_client(StdioServerParameters(
                    command=command, args=args, env=merged_env,
                )) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        self._session = session
                        self._ready.set()
                        await self._shutdown.wait()
            except Exception as ex:
                self._error = ex
                self._ready.set()

        self._task = asyncio.create_task(_run())
        await self._ready.wait()
        if self._error:
            raise self._error

    async def list_tools(self) -> list[tuple[str, str]]:
        """Discover available tools on this server.

        Returns:
            List of (tool_name, tool_description) tuples.
        """
        if not self._session:
            raise RuntimeError(f"MCP client '{self.name}' not connected")
        result = await self._session.list_tools()
        return [(t.name, t.description or "") for t in result.tools]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call a tool and return its result.

        Prefers structuredContent (JSON dict) when available. Falls back to
        concatenated text content. Always use structuredContent directly —
        never json.loads() on text content.

        Args:
            name: Tool name (e.g. "gmail_search").
            arguments: Tool arguments as a dict.

        Returns:
            structuredContent dict if available, else joined text string.
        """
        if not self._session:
            raise RuntimeError(f"MCP client '{self.name}' not connected")
        result = await self._session.call_tool(name, arguments or {})
        # Prefer structuredContent (JSON) over text content
        if result.structuredContent is not None:
            return result.structuredContent
        # Fall back to text content
        parts = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "\n".join(parts) if parts else ""

    async def close(self) -> None:
        """Shut down the MCP server connection gracefully."""
        if self._task is None or self._task.done():
            return
        self._shutdown.set()
        self._task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout=_SHUTDOWN_TIMEOUT)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
