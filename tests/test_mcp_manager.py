"""Tests for McpManager and related helpers."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from micro_x_agent_loop.mcp.mcp_manager import (
    McpManager,
    _build_proxies,
    _mcp_logging_callback,
    _ServerConnection,
    add_notification_channel,
    remove_notification_channel,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_tool(name: str = "tool", description: str = "desc") -> MagicMock:
    t = MagicMock()
    t.name = name
    t.description = description
    t.inputSchema = {"type": "object"}
    t.annotations = None
    t.outputSchema = None
    return t


def _fake_tools_result(*tool_names: str) -> MagicMock:
    res = MagicMock()
    res.tools = [_fake_tool(n) for n in tool_names]
    return res


# ---------------------------------------------------------------------------
# _build_proxies
# ---------------------------------------------------------------------------

class BuildProxiesTests(unittest.TestCase):
    def test_empty_tools(self) -> None:
        session = MagicMock()
        result = _fake_tools_result()
        proxies = _build_proxies("srv", result, session)
        self.assertEqual([], proxies)

    def test_basic_tools(self) -> None:
        session = MagicMock()
        result = _fake_tools_result("read_file", "write_file")
        proxies = _build_proxies("srv", result, session)
        self.assertEqual(2, len(proxies))
        names = {p.name for p in proxies}
        self.assertIn("srv__read_file", names)
        self.assertIn("srv__write_file", names)

    def test_mutating_from_annotations(self) -> None:
        session = MagicMock()
        t = _fake_tool("rm")
        annotations = MagicMock()
        annotations.destructiveHint = True
        t.annotations = annotations
        res = MagicMock()
        res.tools = [t]
        proxies = _build_proxies("srv", res, session)
        self.assertTrue(proxies[0].is_mutating)

    def test_output_schema_propagated(self) -> None:
        session = MagicMock()
        t = _fake_tool("query")
        t.outputSchema = {"type": "object", "properties": {}}
        res = MagicMock()
        res.tools = [t]
        proxies = _build_proxies("srv", res, session)
        self.assertIsNotNone(proxies[0].output_schema)


# ---------------------------------------------------------------------------
# _mcp_logging_callback
# ---------------------------------------------------------------------------

class McpLoggingCallbackTests(unittest.TestCase):
    def test_routes_to_channels(self) -> None:
        channel = MagicMock()
        add_notification_channel(channel)
        try:
            params = MagicMock()
            params.level = "info"
            params.logger = "myserver"
            params.data = "hello"
            asyncio.run(_mcp_logging_callback(params))
            channel.emit_system_message.assert_called_once()
            msg = channel.emit_system_message.call_args[0][0]
            self.assertIn("hello", msg)
            self.assertIn("myserver", msg)
        finally:
            remove_notification_channel(channel)

    def test_fallback_no_channels(self) -> None:
        params = MagicMock()
        params.level = "warning"
        params.logger = None
        params.data = "warn message"
        with patch("micro_x_agent_loop.mcp.mcp_manager.print_through_spinner") as mock_print:
            asyncio.run(_mcp_logging_callback(params))
            mock_print.assert_called_once()

    def test_add_remove_channel(self) -> None:
        channel = MagicMock()
        add_notification_channel(channel)
        remove_notification_channel(channel)
        params = MagicMock()
        params.level = "info"
        params.logger = None
        params.data = "msg"
        # After removal, should NOT call emit on the channel
        with patch("micro_x_agent_loop.mcp.mcp_manager.print_through_spinner"):
            asyncio.run(_mcp_logging_callback(params))
        channel.emit_system_message.assert_not_called()


# ---------------------------------------------------------------------------
# _ServerConnection
# ---------------------------------------------------------------------------

def _make_session_cm(tools_result: MagicMock) -> MagicMock:
    """Build a ClientSession async context manager mock that returns tools."""
    session = MagicMock()
    session.initialize = AsyncMock()
    session.list_tools = AsyncMock(return_value=tools_result)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _make_stdio_cm(session_cm: MagicMock) -> MagicMock:
    """Build a stdio_client async context manager."""
    read_stream = MagicMock()
    write_stream = MagicMock()

    outer_cm = MagicMock()
    outer_cm.__aenter__ = AsyncMock(return_value=(read_stream, write_stream))
    outer_cm.__aexit__ = AsyncMock(return_value=False)
    return outer_cm


class ServerConnectionTests(unittest.TestCase):
    def test_stop_noop_when_no_task(self) -> None:
        conn = _ServerConnection("test")
        asyncio.run(conn.stop())  # Should not raise

    def test_start_unknown_transport(self) -> None:
        async def go() -> None:
            conn = _ServerConnection("test")
            config = {"transport": "ftp"}
            await conn.start(config)
            with self.assertRaises(ValueError):
                await conn.wait_ready()

        asyncio.run(go())

    def test_start_stdio_success(self) -> None:
        async def go() -> None:
            tools_result = _fake_tools_result("foo", "bar")
            session = MagicMock()
            session.initialize = AsyncMock()
            session.list_tools = AsyncMock(return_value=tools_result)

            # Patch at the module level
            with patch("micro_x_agent_loop.mcp.mcp_manager.stdio_client") as mock_stdio, \
                 patch("micro_x_agent_loop.mcp.mcp_manager.ClientSession") as mock_client_cls:

                # stdio_client returns (read_stream, write_stream)
                streams_cm = MagicMock()
                streams_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
                streams_cm.__aexit__ = AsyncMock(return_value=False)
                mock_stdio.return_value = streams_cm

                # ClientSession returns session with initialize, list_tools
                session_cm = MagicMock()
                session_cm.__aenter__ = AsyncMock(return_value=session)
                session_cm.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = session_cm

                conn = _ServerConnection("srv")

                # We need to allow _ready to get set before _shutdown blocks
                async def start_then_stop():
                    await conn.start({"transport": "stdio", "command": "fake-cmd"})
                    await conn.wait_ready()
                    await conn.stop()

                await start_then_stop()
                self.assertEqual(2, len(conn.tools))

        asyncio.run(go())

    def test_start_stdio_connection_error(self) -> None:
        async def go() -> None:
            with patch("micro_x_agent_loop.mcp.mcp_manager.stdio_client") as mock_stdio:
                cm = MagicMock()
                cm.__aenter__ = AsyncMock(side_effect=RuntimeError("connection failed"))
                cm.__aexit__ = AsyncMock(return_value=False)
                mock_stdio.return_value = cm

                conn = _ServerConnection("srv")
                await conn.start({"transport": "stdio", "command": "fake"})
                # wait_ready should raise the stored error
                with self.assertRaises(RuntimeError):
                    await conn.wait_ready()

        asyncio.run(go())

    def test_start_http_success(self) -> None:
        async def go() -> None:
            tools_result = _fake_tools_result("http_tool")
            session = MagicMock()
            session.initialize = AsyncMock()
            session.list_tools = AsyncMock(return_value=tools_result)

            with patch("micro_x_agent_loop.mcp.mcp_manager.streamable_http_client") as mock_http, \
                 patch("micro_x_agent_loop.mcp.mcp_manager.ClientSession") as mock_client_cls:

                streams_cm = MagicMock()
                streams_cm.__aenter__ = AsyncMock(
                    return_value=(MagicMock(), MagicMock(), MagicMock())
                )
                streams_cm.__aexit__ = AsyncMock(return_value=False)
                mock_http.return_value = streams_cm

                session_cm = MagicMock()
                session_cm.__aenter__ = AsyncMock(return_value=session)
                session_cm.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = session_cm

                conn = _ServerConnection("http-srv")
                await conn.start({"transport": "http", "url": "http://localhost:9000"})
                await conn.wait_ready()
                await conn.stop()

                self.assertEqual(1, len(conn.tools))

        asyncio.run(go())


# ---------------------------------------------------------------------------
# McpManager
# ---------------------------------------------------------------------------

class McpManagerTests(unittest.TestCase):
    def test_connect_all_empty(self) -> None:
        async def go() -> None:
            mgr = McpManager({})
            tools = await mgr.connect_all()
            self.assertEqual([], tools)
            await mgr.close()

        asyncio.run(go())

    def test_connect_all_with_server(self) -> None:
        async def go() -> None:
            tools_result = _fake_tools_result("tool1")
            session = MagicMock()
            session.initialize = AsyncMock()
            session.list_tools = AsyncMock(return_value=tools_result)

            with patch("micro_x_agent_loop.mcp.mcp_manager.stdio_client") as mock_stdio, \
                 patch("micro_x_agent_loop.mcp.mcp_manager.ClientSession") as mock_client_cls:

                streams_cm = MagicMock()
                streams_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
                streams_cm.__aexit__ = AsyncMock(return_value=False)
                mock_stdio.return_value = streams_cm

                session_cm = MagicMock()
                session_cm.__aenter__ = AsyncMock(return_value=session)
                session_cm.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = session_cm

                mgr = McpManager({"myserver": {"command": "fake"}})
                tools = await mgr.connect_all()
                await mgr.close()

            self.assertEqual(1, len(tools))
            self.assertEqual("myserver__tool1", tools[0].name)

        asyncio.run(go())

    def test_connect_all_server_fails_gracefully(self) -> None:
        async def go() -> None:
            with patch("micro_x_agent_loop.mcp.mcp_manager.stdio_client") as mock_stdio:
                cm = MagicMock()
                cm.__aenter__ = AsyncMock(side_effect=RuntimeError("fail"))
                cm.__aexit__ = AsyncMock(return_value=False)
                mock_stdio.return_value = cm

                mgr = McpManager({"bad-server": {"command": "fake"}})
                tools = await mgr.connect_all()
                # Failed server contributes no tools but doesn't raise
                self.assertEqual([], tools)

        asyncio.run(go())

    def test_close_empty(self) -> None:
        async def go() -> None:
            mgr = McpManager({})
            await mgr.close()  # should not raise

        asyncio.run(go())

    def test_close_clears_connections(self) -> None:
        async def go() -> None:
            mgr = McpManager({})
            # Manually add a mock connection
            conn = MagicMock()
            conn.name = "fake-conn"
            conn.stop = AsyncMock()
            mgr._connections.append(conn)

            await mgr.close()
            conn.stop.assert_called_once()
            self.assertEqual([], mgr._connections)

        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
