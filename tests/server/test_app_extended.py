"""Extended server app endpoint tests."""

from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient

from micro_x_agent_loop.server.app import create_app

_TEST_CONFIG = os.path.join(os.path.dirname(__file__), "config-test.json")


class SessionEndpointTests(unittest.TestCase):
    def test_get_session_without_memory(self) -> None:
        app = create_app(config_path=_TEST_CONFIG)
        with TestClient(app) as client:
            resp = client.get("/api/sessions/nonexistent")
            # Without memory enabled, returns 404
            self.assertEqual(404, resp.status_code)

    def test_create_session_without_memory(self) -> None:
        app = create_app(config_path=_TEST_CONFIG)
        with TestClient(app) as client:
            resp = client.post("/api/sessions")
            # Without memory enabled, returns 400
            self.assertEqual(400, resp.status_code)

    def test_get_messages_without_memory(self) -> None:
        app = create_app(config_path=_TEST_CONFIG)
        with TestClient(app) as client:
            resp = client.get("/api/sessions/s1/messages")
            self.assertEqual(404, resp.status_code)


class ChatExtendedTests(unittest.TestCase):
    def test_chat_invalid_json_body(self) -> None:
        app = create_app(config_path=_TEST_CONFIG)
        with TestClient(app) as client:
            resp = client.post(
                "/api/chat",
                content=b"not json",
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(400, resp.status_code)


class HealthDetailTests(unittest.TestCase):
    def test_health_shows_tools_count(self) -> None:
        app = create_app(config_path=_TEST_CONFIG)
        with TestClient(app) as client:
            resp = client.get("/api/health")
            data = resp.json()
            self.assertIn("tools", data)
            self.assertIsInstance(data["tools"], int)

    def test_health_shows_memory_flag(self) -> None:
        app = create_app(config_path=_TEST_CONFIG)
        with TestClient(app) as client:
            resp = client.get("/api/health")
            data = resp.json()
            self.assertIn("memory_enabled", data)
            self.assertIsInstance(data["memory_enabled"], bool)

    def test_health_shows_active_sessions(self) -> None:
        app = create_app(config_path=_TEST_CONFIG)
        with TestClient(app) as client:
            resp = client.get("/api/health")
            data = resp.json()
            self.assertIn("active_sessions", data)
            self.assertGreaterEqual(data["active_sessions"], 0)


if __name__ == "__main__":
    unittest.main()
