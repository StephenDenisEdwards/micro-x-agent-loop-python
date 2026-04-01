"""Coverage-focused server app tests — auth edge cases, chat with session, CORS."""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from micro_x_agent_loop.server.app import create_app

_TEST_CONFIG = os.path.join(os.path.dirname(__file__), "config-test.json")


class AuthEdgeCaseTests(unittest.TestCase):
    def test_wrong_bearer_token_rejected(self) -> None:
        app = create_app(config_path=_TEST_CONFIG, api_secret="correct-secret")
        with TestClient(app) as client:
            resp = client.get(
                "/api/sessions",
                headers={"Authorization": "Bearer wrong-secret"},
            )
            self.assertEqual(401, resp.status_code)

    def test_no_auth_header_rejected(self) -> None:
        app = create_app(config_path=_TEST_CONFIG, api_secret="my-secret")
        with TestClient(app) as client:
            resp = client.get("/api/sessions")
            self.assertEqual(401, resp.status_code)

    def test_docs_endpoint_skips_auth(self) -> None:
        app = create_app(config_path=_TEST_CONFIG, api_secret="my-secret")
        with TestClient(app) as client:
            resp = client.get("/docs")
            # FastAPI docs should be accessible without auth
            self.assertIn(resp.status_code, (200, 307))

    def test_openapi_json_skips_auth(self) -> None:
        app = create_app(config_path=_TEST_CONFIG, api_secret="my-secret")
        with TestClient(app) as client:
            resp = client.get("/openapi.json")
            self.assertEqual(200, resp.status_code)


class CorsTests(unittest.TestCase):
    def test_cors_headers_present(self) -> None:
        app = create_app(config_path=_TEST_CONFIG, cors_origins=["http://localhost:3000"])
        with TestClient(app) as client:
            resp = client.options(
                "/api/health",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "GET",
                },
            )
            self.assertIn("access-control-allow-origin", resp.headers)


class ChatWithSessionTests(unittest.TestCase):
    def test_chat_generates_session_id_when_missing(self) -> None:
        """Chat without session_id should generate a UUID."""
        # We need to mock the agent_manager
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=None)

        mock_manager = MagicMock()
        mock_manager.get_or_create = AsyncMock(return_value=mock_agent)
        mock_manager.active_count = 0
        mock_manager.shutdown_all = AsyncMock()

        app = create_app(config_path=_TEST_CONFIG, agent_manager=mock_manager)
        with TestClient(app) as client:
            resp = client.post("/api/chat", json={"message": "hello"})
            self.assertEqual(200, resp.status_code)
            data = resp.json()
            self.assertIn("session_id", data)
            self.assertTrue(len(data["session_id"]) > 0)

    def test_chat_with_explicit_session_id(self) -> None:
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=None)

        mock_manager = MagicMock()
        mock_manager.get_or_create = AsyncMock(return_value=mock_agent)
        mock_manager.active_count = 0
        mock_manager.shutdown_all = AsyncMock()

        app = create_app(config_path=_TEST_CONFIG, agent_manager=mock_manager)
        with TestClient(app) as client:
            resp = client.post(
                "/api/chat",
                json={"message": "hello", "session_id": "my-session"},
            )
            self.assertEqual(200, resp.status_code)
            data = resp.json()
            self.assertEqual("my-session", data["session_id"])


class DeleteSessionTests(unittest.TestCase):
    def test_delete_calls_agent_manager(self) -> None:
        mock_manager = MagicMock()
        mock_manager.destroy = AsyncMock()
        mock_manager.active_count = 0
        mock_manager.shutdown_all = AsyncMock()

        app = create_app(config_path=_TEST_CONFIG, agent_manager=mock_manager)
        with TestClient(app) as client:
            resp = client.delete("/api/sessions/s-123")
            self.assertEqual(200, resp.status_code)
            data = resp.json()
            self.assertEqual("deleted", data["status"])
            self.assertEqual("s-123", data["session_id"])
            mock_manager.destroy.assert_called_once_with("s-123")


class HealthWithBrokerTests(unittest.TestCase):
    def test_health_without_broker_no_broker_key(self) -> None:
        app = create_app(config_path=_TEST_CONFIG)
        with TestClient(app) as client:
            resp = client.get("/api/health")
            data = resp.json()
            self.assertNotIn("broker", data)


class ChatEdgeCases(unittest.TestCase):
    def test_chat_whitespace_only_message(self) -> None:
        """Chat with whitespace-only message returns 400."""
        app = create_app(config_path=_TEST_CONFIG)
        with TestClient(app) as client:
            resp = client.post("/api/chat", json={"message": "   \n\t  "})
            self.assertEqual(400, resp.status_code)


if __name__ == "__main__":
    unittest.main()
