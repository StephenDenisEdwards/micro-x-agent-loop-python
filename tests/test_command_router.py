"""Tests for CommandRouter."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from micro_x_agent_loop.commands.router import CommandRouter


def _make_router() -> tuple[CommandRouter, dict[str, list]]:
    """Create a router with all handlers collecting calls."""
    calls: dict[str, list] = {k: [] for k in (
        "help", "command", "cost", "rewind", "checkpoint", "session",
        "voice", "memory", "tools", "tool", "console_log_level", "debug", "routing", "unknown"
    )}

    async def on_help():
        calls["help"].append(())

    async def on_command(cmd: str) -> str | None:
        calls["command"].append(cmd)
        return None

    async def on_cost(cmd: str) -> None:
        calls["cost"].append(cmd)

    async def on_rewind(cmd: str) -> None:
        calls["rewind"].append(cmd)

    async def on_checkpoint(cmd: str) -> None:
        calls["checkpoint"].append(cmd)

    async def on_session(cmd: str) -> None:
        calls["session"].append(cmd)

    async def on_voice(cmd: str) -> None:
        calls["voice"].append(cmd)

    async def on_memory(cmd: str) -> None:
        calls["memory"].append(cmd)

    async def on_tools(cmd: str) -> None:
        calls["tools"].append(cmd)

    async def on_tool(cmd: str) -> None:
        calls["tool"].append(cmd)

    async def on_console_log_level(cmd: str) -> None:
        calls["console_log_level"].append(cmd)

    async def on_debug(cmd: str) -> None:
        calls["debug"].append(cmd)

    async def on_routing(cmd: str) -> None:
        calls["routing"].append(cmd)

    def on_unknown(cmd: str) -> None:
        calls["unknown"].append(cmd)

    router = CommandRouter(
        on_help=on_help,
        on_rewind=on_rewind,
        on_checkpoint=on_checkpoint,
        on_session=on_session,
        on_voice=on_voice,
        on_cost=on_cost,
        on_memory=on_memory,
        on_tools=on_tools,
        on_tool=on_tool,
        on_command=on_command,
        on_console_log_level=on_console_log_level,
        on_debug=on_debug,
        on_routing=on_routing,
        on_unknown=on_unknown,
    )
    return router, calls


class CommandRouterTests(unittest.TestCase):
    def test_non_command_returns_false(self) -> None:
        router, calls = _make_router()
        result = asyncio.run(router.try_handle("hello world"))
        self.assertFalse(result)

    def test_help(self) -> None:
        router, calls = _make_router()
        result = asyncio.run(router.try_handle("/help"))
        self.assertTrue(result)
        self.assertEqual(1, len(calls["help"]))

    def test_command_returns_prompt(self) -> None:
        async def on_command(cmd: str) -> str | None:
            return "run this prompt"

        router, calls = _make_router()
        router._on_command = on_command
        result = asyncio.run(router.try_handle("/command greet"))
        self.assertEqual("run this prompt", result)

    def test_command_returns_true_when_none(self) -> None:
        router, calls = _make_router()
        result = asyncio.run(router.try_handle("/command"))
        self.assertTrue(result)
        self.assertEqual(1, len(calls["command"]))

    def test_cost(self) -> None:
        router, calls = _make_router()
        result = asyncio.run(router.try_handle("/cost"))
        self.assertTrue(result)
        self.assertEqual(1, len(calls["cost"]))

    def test_rewind(self) -> None:
        router, calls = _make_router()
        result = asyncio.run(router.try_handle("/rewind abc"))
        self.assertTrue(result)
        self.assertEqual(1, len(calls["rewind"]))

    def test_checkpoint(self) -> None:
        router, calls = _make_router()
        result = asyncio.run(router.try_handle("/checkpoint list"))
        self.assertTrue(result)
        self.assertEqual(1, len(calls["checkpoint"]))

    def test_session(self) -> None:
        router, calls = _make_router()
        result = asyncio.run(router.try_handle("/session new"))
        self.assertTrue(result)
        self.assertEqual(1, len(calls["session"]))

    def test_voice(self) -> None:
        router, calls = _make_router()
        result = asyncio.run(router.try_handle("/voice status"))
        self.assertTrue(result)
        self.assertEqual(1, len(calls["voice"]))

    def test_memory(self) -> None:
        router, calls = _make_router()
        result = asyncio.run(router.try_handle("/memory list"))
        self.assertTrue(result)
        self.assertEqual(1, len(calls["memory"]))

    def test_tools(self) -> None:
        router, calls = _make_router()
        result = asyncio.run(router.try_handle("/tools mcp"))
        self.assertTrue(result)
        self.assertEqual(1, len(calls["tools"]))

    def test_tool(self) -> None:
        router, calls = _make_router()
        result = asyncio.run(router.try_handle("/tool foo"))
        self.assertTrue(result)
        self.assertEqual(1, len(calls["tool"]))

    def test_console_log_level(self) -> None:
        router, calls = _make_router()
        result = asyncio.run(router.try_handle("/console-log-level DEBUG"))
        self.assertTrue(result)
        self.assertEqual(1, len(calls["console_log_level"]))

    def test_debug(self) -> None:
        router, calls = _make_router()
        result = asyncio.run(router.try_handle("/debug show-api-payload"))
        self.assertTrue(result)
        self.assertEqual(1, len(calls["debug"]))

    def test_unknown_command(self) -> None:
        router, calls = _make_router()
        result = asyncio.run(router.try_handle("/frobnitz"))
        self.assertTrue(result)
        self.assertEqual(1, len(calls["unknown"]))

    def test_whitespace_stripped(self) -> None:
        router, calls = _make_router()
        result = asyncio.run(router.try_handle("   /help   "))
        self.assertTrue(result)
        self.assertEqual(1, len(calls["help"]))


if __name__ == "__main__":
    unittest.main()
