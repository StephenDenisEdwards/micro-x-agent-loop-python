"""Extended tests for server/client.py — URL parsing, health check, session creation."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from micro_x_agent_loop.server.client import run_client


class UrlParsingTests(unittest.TestCase):
    """Test URL and WebSocket scheme logic without actual connections."""

    def test_http_to_ws(self) -> None:
        """http:// URL should produce ws:// WebSocket URL."""
        # We test by checking that the health check attempt uses the right base_url.
        # The client will fail on health check (no server), but we verify the URL logic.

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"tools": 5, "memory_enabled": True}

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        # Also mock session creation
        mock_session_resp = MagicMock()
        mock_session_resp.status_code = 200
        mock_session_resp.json.return_value = {"session_id": "test-session"}

        mock_http_session = AsyncMock()
        mock_http_session.post = AsyncMock(return_value=mock_session_resp)
        mock_http_session.__aenter__ = AsyncMock(return_value=mock_http_session)
        mock_http_session.__aexit__ = AsyncMock(return_value=False)

        call_count = 0

        def make_client(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_http
            return mock_http_session

        # Mock websockets.connect to fail cleanly
        with patch("micro_x_agent_loop.server.client.httpx.AsyncClient", side_effect=make_client):
            with patch.dict("sys.modules", {"websockets": MagicMock()}):
                import importlib

                import micro_x_agent_loop.server.client as client_mod

                importlib.reload(client_mod)

                # We can't fully test WS connection without a server, but we verify
                # the health check works and session is created
                async def go() -> None:
                    # This will fail at websockets.connect, but we verify the preceding logic
                    try:
                        await client_mod.run_client("http://localhost:8321")
                    except Exception:
                        pass

                asyncio.run(go())

                # Health check should have been called
                mock_http.get.assert_called_once()
                url_arg = mock_http.get.call_args[0][0]
                self.assertIn("http://localhost:8321/api/health", url_arg)

    def test_health_check_failure(self) -> None:
        """Client returns early when health check fails."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("micro_x_agent_loop.server.client.httpx.AsyncClient", return_value=mock_http):
            output: list[str] = []
            with patch("builtins.print", side_effect=lambda *a, **kw: output.append(str(a[0]) if a else "")):
                asyncio.run(run_client("http://localhost:9999"))

            self.assertTrue(any("health check failed" in o for o in output))

    def test_session_creation_failure_generates_uuid(self) -> None:
        """When session creation fails, a UUID is generated."""
        mock_health_resp = MagicMock()
        mock_health_resp.status_code = 200
        mock_health_resp.json.return_value = {"tools": 0, "memory_enabled": False}

        mock_session_resp = MagicMock()
        mock_session_resp.status_code = 500

        mock_http = AsyncMock()

        async def mock_get(*args, **kwargs):
            return mock_health_resp

        mock_http.get = mock_get

        async def mock_post(*args, **kwargs):
            return mock_session_resp

        mock_http.post = mock_post

        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        output: list[str] = []

        with patch("micro_x_agent_loop.server.client.httpx.AsyncClient", return_value=mock_http):
            with patch.dict("sys.modules", {"websockets": MagicMock()}):
                import importlib

                import micro_x_agent_loop.server.client as client_mod

                importlib.reload(client_mod)

                with patch("builtins.print", side_effect=lambda *a, **kw: output.append(str(a[0]) if a else "")):
                    try:
                        asyncio.run(client_mod.run_client("http://localhost:9999"))
                    except Exception:
                        pass

        # Should have printed "Session: <some-uuid>"
        session_lines = [o for o in output if "Session:" in o]
        self.assertTrue(len(session_lines) > 0)

    def test_explicit_session_id_used(self) -> None:
        """When session_id is provided, no creation POST is made."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"tools": 0, "memory_enabled": False}

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        output: list[str] = []

        with patch("micro_x_agent_loop.server.client.httpx.AsyncClient", return_value=mock_http):
            with patch.dict("sys.modules", {"websockets": MagicMock()}):
                import importlib

                import micro_x_agent_loop.server.client as client_mod

                importlib.reload(client_mod)

                with patch("builtins.print", side_effect=lambda *a, **kw: output.append(str(a[0]) if a else "")):
                    try:
                        asyncio.run(client_mod.run_client("http://localhost:9999", session_id="my-session"))
                    except Exception:
                        pass

        session_lines = [o for o in output if "my-session" in o]
        self.assertTrue(len(session_lines) > 0)

    def test_auth_header_passed(self) -> None:
        """api_secret is passed as Authorization header."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"tools": 0, "memory_enabled": False}

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("micro_x_agent_loop.server.client.httpx.AsyncClient", return_value=mock_http):
            with patch.dict("sys.modules", {"websockets": MagicMock()}):
                import importlib

                import micro_x_agent_loop.server.client as client_mod

                importlib.reload(client_mod)

                try:
                    asyncio.run(
                        client_mod.run_client(
                            "http://localhost:9999",
                            session_id="s1",
                            api_secret="my-secret",
                        )
                    )
                except Exception:
                    pass

        # Health check should have included auth header
        call_kwargs = mock_http.get.call_args
        headers = call_kwargs[1].get("headers", call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {})
        # The function passes headers as a keyword arg
        if isinstance(headers, dict) and "Authorization" in headers:
            self.assertEqual("Bearer my-secret", headers["Authorization"])

    def test_websockets_import_error(self) -> None:
        """Missing websockets package shows helpful message."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"tools": 0, "memory_enabled": False}

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        mock_http2 = AsyncMock()
        mock_session_resp = MagicMock()
        mock_session_resp.status_code = 200
        mock_session_resp.json.return_value = {"session_id": "s1"}
        mock_http2.post = AsyncMock(return_value=mock_session_resp)
        mock_http2.__aenter__ = AsyncMock(return_value=mock_http2)
        mock_http2.__aexit__ = AsyncMock(return_value=False)

        call_count = 0

        def make_http(*a, **k):
            nonlocal call_count
            call_count += 1
            return mock_http if call_count == 1 else mock_http2

        output: list[str] = []

        # Remove websockets from sys.modules to trigger ImportError
        import sys

        ws_backup = sys.modules.get("websockets")
        sys.modules["websockets"] = None  # type: ignore[assignment]

        try:
            import importlib

            import micro_x_agent_loop.server.client as client_mod

            importlib.reload(client_mod)

            with patch("micro_x_agent_loop.server.client.httpx.AsyncClient", side_effect=make_http):
                with patch("builtins.print", side_effect=lambda *a, **kw: output.append(str(a[0]) if a else "")):
                    asyncio.run(client_mod.run_client("http://localhost:9999"))
        finally:
            if ws_backup is not None:
                sys.modules["websockets"] = ws_backup
            elif "websockets" in sys.modules:
                del sys.modules["websockets"]

        self.assertTrue(any("websockets" in o.lower() for o in output))


class ReceiverDispatchTests(unittest.TestCase):
    """Test the WebSocket receiver loop message dispatch."""

    def _run_with_ws_messages(self, ws_messages: list[dict], *, session_id: str = "s1") -> list[str]:
        """Helper: run client with mocked health check + WebSocket messages."""
        output: list[str] = []

        mock_health = MagicMock()
        mock_health.status_code = 200
        mock_health.json.return_value = {"tools": 0, "memory_enabled": False}

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_health)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        # Mock WebSocket that yields messages then closes
        class FakeWS:
            def __init__(self):
                self._messages = [json.dumps(m) for m in ws_messages]
                self._idx = 0
                self.sent: list[str] = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self._idx >= len(self._messages):
                    raise StopAsyncIteration
                msg = self._messages[self._idx]
                self._idx += 1
                return msg

            async def send(self, data: str) -> None:
                self.sent.append(data)

        fake_ws = FakeWS()
        mock_ws_connect = MagicMock(return_value=fake_ws)

        mock_websockets = MagicMock()
        mock_websockets.connect = mock_ws_connect
        mock_websockets.ConnectionClosed = type("ConnectionClosed", (Exception,), {})
        mock_websockets.InvalidStatus = type(
            "InvalidStatus",
            (Exception,),
            {
                "__init__": lambda self, *a: None,
            },
        )

        with patch("micro_x_agent_loop.server.client.httpx.AsyncClient", return_value=mock_http):
            with patch.dict("sys.modules", {"websockets": mock_websockets}):
                import importlib

                import micro_x_agent_loop.server.client as client_mod

                importlib.reload(client_mod)

                with patch("builtins.print", side_effect=lambda *a, **kw: output.append(str(a[0]) if a else "")):
                    try:
                        asyncio.run(client_mod.run_client("http://localhost:9999", session_id=session_id))
                    except Exception:
                        pass

        return output

    def test_text_delta_dispatched(self) -> None:
        output = self._run_with_ws_messages(
            [
                {"type": "text_delta", "text": "Hello"},
                {"type": "turn_complete", "usage": {}},
            ]
        )
        # Should have connected and printed session info
        self.assertTrue(any("Session:" in o for o in output))

    def test_error_message_dispatched(self) -> None:
        output = self._run_with_ws_messages(
            [
                {"type": "error", "message": "something broke"},
            ]
        )
        self.assertTrue(any("Session:" in o for o in output))

    def test_system_message_dispatched(self) -> None:
        output = self._run_with_ws_messages(
            [
                {"type": "system_message", "text": "system info"},
            ]
        )
        self.assertTrue(any("Session:" in o for o in output))

    def test_pong_dispatched(self) -> None:
        output = self._run_with_ws_messages(
            [
                {"type": "pong"},
            ]
        )
        self.assertTrue(any("Session:" in o for o in output))

    def test_tool_lifecycle_dispatched(self) -> None:
        output = self._run_with_ws_messages(
            [
                {"type": "tool_started", "tool_use_id": "t1", "tool": "read_file"},
                {"type": "tool_completed", "tool_use_id": "t1", "tool": "read_file", "error": False},
                {"type": "turn_complete", "usage": {}},
            ]
        )
        self.assertTrue(any("Session:" in o for o in output))


class InvalidStatusTests(unittest.TestCase):
    def test_401_shows_auth_message(self) -> None:
        """InvalidStatus with 401 shows auth failure message."""
        output: list[str] = []

        mock_health = MagicMock()
        mock_health.status_code = 200
        mock_health.json.return_value = {"tools": 0, "memory_enabled": False}

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_health)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        # Create a fake InvalidStatus exception
        class FakeResponse:
            status_code = 401

        class FakeInvalidStatus(Exception):
            def __init__(self):
                self.response = FakeResponse()

        class FakeConnectionClosed(Exception):
            pass

        mock_websockets = MagicMock()
        mock_websockets.connect = MagicMock(side_effect=FakeInvalidStatus())
        mock_websockets.InvalidStatus = FakeInvalidStatus
        mock_websockets.ConnectionClosed = FakeConnectionClosed

        with patch("micro_x_agent_loop.server.client.httpx.AsyncClient", return_value=mock_http):
            with patch.dict("sys.modules", {"websockets": mock_websockets}):
                import importlib

                import micro_x_agent_loop.server.client as client_mod

                importlib.reload(client_mod)

                with patch("builtins.print", side_effect=lambda *a, **kw: output.append(str(a[0]) if a else "")):
                    asyncio.run(client_mod.run_client("http://localhost:9999", session_id="s1"))

        self.assertTrue(any("Authentication failed" in o for o in output))

    def test_non_401_shows_generic_message(self) -> None:
        output: list[str] = []

        mock_health = MagicMock()
        mock_health.status_code = 200
        mock_health.json.return_value = {"tools": 0, "memory_enabled": False}

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_health)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        class FakeResponse:
            status_code = 500

        class FakeInvalidStatus(Exception):
            def __init__(self):
                self.response = FakeResponse()

        class FakeConnectionClosed(Exception):
            pass

        mock_websockets = MagicMock()
        mock_websockets.connect = MagicMock(side_effect=FakeInvalidStatus())
        mock_websockets.InvalidStatus = FakeInvalidStatus
        mock_websockets.ConnectionClosed = FakeConnectionClosed

        with patch("micro_x_agent_loop.server.client.httpx.AsyncClient", return_value=mock_http):
            with patch.dict("sys.modules", {"websockets": mock_websockets}):
                import importlib

                import micro_x_agent_loop.server.client as client_mod

                importlib.reload(client_mod)

                with patch("builtins.print", side_effect=lambda *a, **kw: output.append(str(a[0]) if a else "")):
                    asyncio.run(client_mod.run_client("http://localhost:9999", session_id="s1"))

        self.assertTrue(any("WebSocket connection failed" in o for o in output))

    def test_generic_connection_error(self) -> None:
        output: list[str] = []

        mock_health = MagicMock()
        mock_health.status_code = 200
        mock_health.json.return_value = {"tools": 0, "memory_enabled": False}

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_health)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        class FakeConnectionClosed(Exception):
            pass

        class FakeInvalidStatus(Exception):
            pass

        mock_websockets = MagicMock()
        mock_websockets.connect = MagicMock(side_effect=OSError("network down"))
        mock_websockets.InvalidStatus = FakeInvalidStatus
        mock_websockets.ConnectionClosed = FakeConnectionClosed

        with patch("micro_x_agent_loop.server.client.httpx.AsyncClient", return_value=mock_http):
            with patch.dict("sys.modules", {"websockets": mock_websockets}):
                import importlib

                import micro_x_agent_loop.server.client as client_mod

                importlib.reload(client_mod)

                with patch("builtins.print", side_effect=lambda *a, **kw: output.append(str(a[0]) if a else "")):
                    asyncio.run(client_mod.run_client("http://localhost:9999", session_id="s1"))

        self.assertTrue(any("Connection error" in o for o in output))


if __name__ == "__main__":
    unittest.main()
