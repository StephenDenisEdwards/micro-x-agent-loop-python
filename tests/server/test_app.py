"""Tests for the API server FastAPI app."""

from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient

from micro_x_agent_loop.server.app import create_app

_TEST_CONFIG = os.path.join(os.path.dirname(__file__), "config-test.json")


class TestHealthEndpoint(unittest.TestCase):
    def test_health_returns_ok(self) -> None:
        app = create_app(config_path=_TEST_CONFIG)
        with TestClient(app) as client:
            resp = client.get("/api/health")
            self.assertEqual(200, resp.status_code)
            data = resp.json()
            self.assertEqual("ok", data["status"])


class TestAuthMiddleware(unittest.TestCase):
    def test_unauthenticated_request_rejected(self) -> None:
        app = create_app(config_path=_TEST_CONFIG, api_secret="test-secret")
        with TestClient(app) as client:
            resp = client.get("/api/sessions")
            self.assertEqual(401, resp.status_code)

    def test_authenticated_request_passes(self) -> None:
        app = create_app(config_path=_TEST_CONFIG, api_secret="test-secret")
        with TestClient(app) as client:
            resp = client.get(
                "/api/sessions",
                headers={"Authorization": "Bearer test-secret"},
            )
            self.assertEqual(200, resp.status_code)

    def test_health_skips_auth(self) -> None:
        app = create_app(config_path=_TEST_CONFIG, api_secret="test-secret")
        with TestClient(app) as client:
            resp = client.get("/api/health")
            self.assertEqual(200, resp.status_code)


class TestSessionEndpoints(unittest.TestCase):
    def test_list_sessions_empty(self) -> None:
        app = create_app(config_path=_TEST_CONFIG)
        with TestClient(app) as client:
            resp = client.get("/api/sessions")
            self.assertEqual(200, resp.status_code)
            data = resp.json()
            self.assertIn("sessions", data)

    def test_delete_session(self) -> None:
        app = create_app(config_path=_TEST_CONFIG)
        with TestClient(app) as client:
            resp = client.delete("/api/sessions/nonexistent")
            self.assertEqual(200, resp.status_code)
            data = resp.json()
            self.assertEqual("deleted", data["status"])


class TestChatEndpoint(unittest.TestCase):
    def test_chat_requires_message(self) -> None:
        app = create_app(config_path=_TEST_CONFIG)
        with TestClient(app) as client:
            resp = client.post("/api/chat", json={})
            self.assertEqual(400, resp.status_code)

    def test_chat_rejects_empty_message(self) -> None:
        app = create_app(config_path=_TEST_CONFIG)
        with TestClient(app) as client:
            resp = client.post("/api/chat", json={"message": "  "})
            self.assertEqual(400, resp.status_code)


class TestCliArgParsing(unittest.TestCase):
    def test_parse_server_flag(self) -> None:
        import sys
        original = sys.argv
        try:
            sys.argv = ["prog", "--server", "start"]
            from micro_x_agent_loop.__main__ import _parse_cli_args
            args = _parse_cli_args()
            self.assertEqual(["start"], args["server"])
        finally:
            sys.argv = original

    def test_parse_server_no_subcommand(self) -> None:
        import sys
        original = sys.argv
        try:
            sys.argv = ["prog", "--server"]
            from micro_x_agent_loop.__main__ import _parse_cli_args
            args = _parse_cli_args()
            self.assertEqual([], args["server"])
        finally:
            sys.argv = original


if __name__ == "__main__":
    unittest.main()
