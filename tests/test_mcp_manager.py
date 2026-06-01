"""Tests for McpManager and related helpers."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from micro_x_agent_loop.mcp.mcp_manager import (
    McpManager,
    _build_proxies,
    _build_url,
    _extract_port,
    _mcp_logging_callback,
    _ServerConnection,
    _wait_for_port,
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
            with (
                patch("micro_x_agent_loop.mcp.mcp_manager.stdio_client") as mock_stdio,
                patch("micro_x_agent_loop.mcp.mcp_manager.ClientSession") as mock_client_cls,
            ):
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

    def test_start_stdio_injects_resolved_config_env(self) -> None:
        """_run_stdio must forward the Agent's resolved config to spawned servers
        via MICRO_X_AGENT_CONFIG_JSON, layered after the per-server env merge."""
        async def go() -> None:
            tools_result = _fake_tools_result("t")
            session = MagicMock()
            session.initialize = AsyncMock()
            session.list_tools = AsyncMock(return_value=tools_result)

            with (
                patch("micro_x_agent_loop.mcp.mcp_manager.stdio_client") as mock_stdio,
                patch("micro_x_agent_loop.mcp.mcp_manager.ClientSession") as mock_client_cls,
            ):
                streams_cm = MagicMock()
                streams_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
                streams_cm.__aexit__ = AsyncMock(return_value=False)
                mock_stdio.return_value = streams_cm

                session_cm = MagicMock()
                session_cm.__aenter__ = AsyncMock(return_value=session)
                session_cm.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = session_cm

                resolved_config = {
                    "WorkingDirectory": "/work",
                    "McpServers": {"google": {"command": "node"}},
                }
                conn = _ServerConnection("srv")
                await conn.start(
                    {
                        "transport": "stdio",
                        "command": "fake",
                        "env": {"PER_SERVER": "yes"},
                    },
                    resolved_config=resolved_config,
                )
                await conn.wait_ready()
                await conn.stop()

                params = mock_stdio.call_args[0][0]
                self.assertEqual("yes", params.env["PER_SERVER"])
                self.assertEqual(
                    resolved_config,
                    json.loads(params.env["MICRO_X_AGENT_CONFIG_JSON"]),
                )

        asyncio.run(go())

    def test_start_stdio_no_env_injection_when_no_resolved_config(self) -> None:
        """When resolved_config is omitted, MICRO_X_AGENT_CONFIG_JSON must not be set."""
        async def go() -> None:
            tools_result = _fake_tools_result("t")
            session = MagicMock()
            session.initialize = AsyncMock()
            session.list_tools = AsyncMock(return_value=tools_result)

            with (
                patch("micro_x_agent_loop.mcp.mcp_manager.stdio_client") as mock_stdio,
                patch("micro_x_agent_loop.mcp.mcp_manager.ClientSession") as mock_client_cls,
                patch.dict("os.environ", {}, clear=True),
            ):
                streams_cm = MagicMock()
                streams_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
                streams_cm.__aexit__ = AsyncMock(return_value=False)
                mock_stdio.return_value = streams_cm

                session_cm = MagicMock()
                session_cm.__aenter__ = AsyncMock(return_value=session)
                session_cm.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = session_cm

                conn = _ServerConnection("srv")
                await conn.start({"transport": "stdio", "command": "fake"})
                await conn.wait_ready()
                await conn.stop()

                params = mock_stdio.call_args[0][0]
                self.assertNotIn("MICRO_X_AGENT_CONFIG_JSON", params.env)

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

            with (
                patch("micro_x_agent_loop.mcp.mcp_manager.streamable_http_client") as mock_http,
                patch("micro_x_agent_loop.mcp.mcp_manager.ClientSession") as mock_client_cls,
            ):
                streams_cm = MagicMock()
                streams_cm.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
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


class IsDisabledTests(unittest.TestCase):
    """A profile disables a Base server via false/null/{enabled:false}."""

    def test_false_is_disabled(self) -> None:
        self.assertTrue(McpManager._is_disabled(False))

    def test_none_is_disabled(self) -> None:
        self.assertTrue(McpManager._is_disabled(None))

    def test_enabled_false_dict_is_disabled(self) -> None:
        self.assertTrue(McpManager._is_disabled({"enabled": False, "command": "x"}))

    def test_normal_config_is_enabled(self) -> None:
        self.assertFalse(McpManager._is_disabled({"command": "node", "args": []}))

    def test_enabled_true_dict_is_enabled(self) -> None:
        self.assertFalse(McpManager._is_disabled({"enabled": True, "command": "x"}))

    def test_connect_all_skips_disabled_servers(self) -> None:
        async def go() -> None:
            # Two disabled entries + one empty-but-enabled; none should connect,
            # and no exception should be raised for the disabled ones.
            mgr = McpManager({"discord": False, "playwright": {"enabled": False}})
            tools = await mgr.connect_all()
            self.assertEqual([], tools)
            await mgr.close()

        asyncio.run(go())


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

            with (
                patch("micro_x_agent_loop.mcp.mcp_manager.stdio_client") as mock_stdio,
                patch("micro_x_agent_loop.mcp.mcp_manager.ClientSession") as mock_client_cls,
            ):
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


# ---------------------------------------------------------------------------
# HTTP/SSE transport helpers
# ---------------------------------------------------------------------------


class ExtractPortTests(unittest.TestCase):
    def test_explicit_port_field(self) -> None:
        self.assertEqual(8081, _extract_port({"port": 8081}))

    def test_explicit_port_field_string(self) -> None:
        self.assertEqual(8081, _extract_port({"port": "8081"}))

    def test_inferred_from_args(self) -> None:
        config = {"args": ["-y", "@playwright/mcp", "--port", "9000", "--browser", "msedge"]}
        self.assertEqual(9000, _extract_port(config))

    def test_explicit_field_wins_over_args(self) -> None:
        config = {"port": 1234, "args": ["--port", "5678"]}
        self.assertEqual(1234, _extract_port(config))

    def test_no_port_raises(self) -> None:
        with self.assertRaises(ValueError):
            _extract_port({"args": ["-y", "@playwright/mcp"]})

    def test_dangling_port_flag_raises(self) -> None:
        # `--port` at the end of args with no value
        with self.assertRaises(ValueError):
            _extract_port({"args": ["-y", "@playwright/mcp", "--port"]})


class BuildUrlTests(unittest.TestCase):
    def test_explicit_url_wins(self) -> None:
        self.assertEqual(
            "http://example.com/sse",
            _build_url({"url": "http://example.com/sse"}, "/ignored"),
        )

    def test_inferred_default_host(self) -> None:
        config = {"port": 8081}
        self.assertEqual("http://localhost:8081/sse", _build_url(config, "/sse"))

    def test_inferred_custom_host(self) -> None:
        config = {"port": 8081, "host": "0.0.0.0"}
        self.assertEqual("http://0.0.0.0:8081/sse", _build_url(config, "/sse"))

    def test_empty_path(self) -> None:
        self.assertEqual("http://localhost:8081", _build_url({"port": 8081}, ""))


class WaitForPortTests(unittest.TestCase):
    @staticmethod
    def _open_listening_socket() -> tuple[Any, int]:
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        return sock, port

    def test_succeeds_when_port_listening(self) -> None:
        async def go() -> None:
            sock, port = self._open_listening_socket()
            try:
                # Should return without raising — the port accepts connections.
                await _wait_for_port("127.0.0.1", port, timeout=2.0)
            finally:
                sock.close()

        asyncio.run(go())

    def test_times_out_when_port_closed(self) -> None:
        async def go() -> None:
            # Bind to grab a free port, then close so it's NOT in use.
            sock, port = self._open_listening_socket()
            sock.close()
            with self.assertRaises(TimeoutError):
                await _wait_for_port("127.0.0.1", port, timeout=0.5)

        asyncio.run(go())


# ---------------------------------------------------------------------------
# transport switching in start()
# ---------------------------------------------------------------------------


class StartTransportSwitchTests(unittest.TestCase):
    """Verify start() dispatches to the right _run_* method by transport."""

    @staticmethod
    def _setup_mocks(conn: _ServerConnection) -> tuple[AsyncMock, AsyncMock, AsyncMock]:
        stdio = AsyncMock()
        sse = AsyncMock()
        http = AsyncMock()
        conn._run_stdio = stdio  # type: ignore[method-assign]
        conn._run_sse = sse  # type: ignore[method-assign]
        conn._run_http = http  # type: ignore[method-assign]
        return stdio, sse, http

    def test_default_transport_is_stdio(self) -> None:
        async def go() -> None:
            conn = _ServerConnection("srv")
            stdio, sse, http = self._setup_mocks(conn)
            await conn.start({"command": "x"})
            await asyncio.wait_for(conn._task, timeout=1.0)
            stdio.assert_called_once()
            sse.assert_not_called()
            http.assert_not_called()

        asyncio.run(go())

    def test_sse_transport_dispatches(self) -> None:
        async def go() -> None:
            conn = _ServerConnection("srv")
            stdio, sse, http = self._setup_mocks(conn)
            await conn.start({"transport": "sse", "command": "x", "port": 8081})
            await asyncio.wait_for(conn._task, timeout=1.0)
            sse.assert_called_once()
            stdio.assert_not_called()
            http.assert_not_called()

        asyncio.run(go())

    def test_http_transport_dispatches(self) -> None:
        async def go() -> None:
            conn = _ServerConnection("srv")
            stdio, sse, http = self._setup_mocks(conn)
            await conn.start({"transport": "http", "url": "http://x"})
            await asyncio.wait_for(conn._task, timeout=1.0)
            http.assert_called_once()
            stdio.assert_not_called()
            sse.assert_not_called()

        asyncio.run(go())

    def test_unknown_transport_records_error(self) -> None:
        async def go() -> None:
            conn = _ServerConnection("srv")
            await conn.start({"transport": "carrier-pigeon"})
            with self.assertRaises(ValueError):
                await conn.wait_ready()

        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
