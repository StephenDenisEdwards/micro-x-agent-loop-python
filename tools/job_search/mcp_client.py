"""Lightweight MCP stdio client for connecting to MCP servers and calling tools."""

import asyncio
import os
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_SHUTDOWN_TIMEOUT = 5.0


class McpClient:
    """Connects to an MCP server via stdio and provides tool calling.

    Uses the same task-based lifecycle as mcp_manager.py: the stdio_client
    context is held open inside an asyncio.Task, controlled by an Event.
    """

    def __init__(self, name: str):
        self.name = name
        self._session: ClientSession | None = None
        self._ready = asyncio.Event()
        self._shutdown = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._error: Exception | None = None

    async def connect(self, command: str, args: list[str], env: dict[str, str] | None = None) -> None:
        """Start the MCP server process and initialize the session."""
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

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call a tool and return structuredContent (JSON) if available, else text."""
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
        """Shut down the MCP server connection."""
        if self._task is None or self._task.done():
            return
        self._shutdown.set()
        self._task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout=_SHUTDOWN_TIMEOUT)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
