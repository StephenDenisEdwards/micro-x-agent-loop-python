"""Tests for the Python client SDK."""

from __future__ import annotations

import asyncio
import os
import unittest

from micro_x_agent_loop.server.sdk import AgentClient, ChatResponse, HealthStatus, SessionInfo

_TEST_CONFIG = os.path.join(os.path.dirname(__file__), "config-test.json")


class TestSdkDataClasses(unittest.TestCase):
    def test_chat_response(self) -> None:
        r = ChatResponse(session_id="s1", text="hello", errors=None)
        self.assertEqual("s1", r.session_id)
        self.assertEqual("hello", r.text)
        self.assertIsNone(r.errors)

    def test_health_status(self) -> None:
        h = HealthStatus(status="ok", active_sessions=2, tools=5, memory_enabled=True)
        self.assertEqual("ok", h.status)
        self.assertEqual(2, h.active_sessions)
        self.assertIsNone(h.broker)

    def test_session_info(self) -> None:
        s = SessionInfo(session_id="s1", raw={"session_id": "s1"})
        self.assertEqual("s1", s.session_id)


class TestSdkClientContextManager(unittest.TestCase):
    def test_client_requires_context_manager(self) -> None:
        client = AgentClient("http://localhost:9999")
        with self.assertRaises(RuntimeError):
            asyncio.run(client.health())


class TestSdkAgainstTestServer(unittest.TestCase):
    """Integration tests using FastAPI TestClient (synchronous).

    These test the SDK's HTTP methods against the real app, but through
    httpx's transport layer rather than a network socket.
    """

    def _make_app(self):  # type: ignore[no-untyped-def]
        from micro_x_agent_loop.server.app import create_app
        return create_app(config_path=_TEST_CONFIG)

    def test_health_via_sdk(self) -> None:
        from fastapi.testclient import TestClient as FastAPITestClient

        app = self._make_app()
        with FastAPITestClient(app) as test_client:
            # Use the test client's transport with httpx
            resp = test_client.get("/api/health")
            self.assertEqual(200, resp.status_code)
            data = resp.json()
            self.assertEqual("ok", data["status"])

    def test_chat_requires_message_via_sdk(self) -> None:
        from fastapi.testclient import TestClient as FastAPITestClient

        app = self._make_app()
        with FastAPITestClient(app) as test_client:
            resp = test_client.post("/api/chat", json={})
            self.assertEqual(400, resp.status_code)

    def test_sessions_list_via_sdk(self) -> None:
        from fastapi.testclient import TestClient as FastAPITestClient

        app = self._make_app()
        with FastAPITestClient(app) as test_client:
            resp = test_client.get("/api/sessions")
            self.assertEqual(200, resp.status_code)
            data = resp.json()
            self.assertIn("sessions", data)

    def test_delete_session_via_sdk(self) -> None:
        from fastapi.testclient import TestClient as FastAPITestClient

        app = self._make_app()
        with FastAPITestClient(app) as test_client:
            resp = test_client.delete("/api/sessions/test-session")
            self.assertEqual(200, resp.status_code)


class TestSdkConnectionError(unittest.TestCase):
    def test_health_connection_error(self) -> None:
        async def go() -> None:
            async with AgentClient("http://127.0.0.1:19998") as client:
                with self.assertRaises(httpx.ConnectError):
                    await client.health()

        import httpx
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
