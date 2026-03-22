"""Tests for broker routes integrated into the API server."""

from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient

from micro_x_agent_loop.server.app import create_app

_TEST_CONFIG = os.path.join(os.path.dirname(__file__), "config-test-broker.json")


class TestBrokerHealthEndpoint(unittest.TestCase):
    def test_health_includes_broker_status(self) -> None:
        app = create_app(config_path=_TEST_CONFIG, broker_enabled=True)
        with TestClient(app) as client:
            resp = client.get("/api/health")
            self.assertEqual(200, resp.status_code)
            data = resp.json()
            self.assertEqual("ok", data["status"])
            self.assertIn("broker", data)
            self.assertTrue(data["broker"]["enabled"])
            self.assertIn("jobs_total", data["broker"])
            self.assertIn("channels", data["broker"])

    def test_health_without_broker(self) -> None:
        app = create_app(config_path=_TEST_CONFIG, broker_enabled=False)
        with TestClient(app) as client:
            resp = client.get("/api/health")
            data = resp.json()
            self.assertNotIn("broker", data)


class TestBrokerJobsEndpoint(unittest.TestCase):
    def test_list_jobs_empty(self) -> None:
        app = create_app(config_path=_TEST_CONFIG, broker_enabled=True)
        with TestClient(app) as client:
            resp = client.get("/api/jobs")
            self.assertEqual(200, resp.status_code)
            data = resp.json()
            self.assertIsInstance(data, list)

    def test_jobs_404_without_broker(self) -> None:
        app = create_app(config_path=_TEST_CONFIG, broker_enabled=False)
        with TestClient(app) as client:
            resp = client.get("/api/jobs")
            # Should get 404 since broker routes are not mounted
            self.assertEqual(404, resp.status_code)


class TestBrokerRunsEndpoint(unittest.TestCase):
    def test_get_run_not_found(self) -> None:
        app = create_app(config_path=_TEST_CONFIG, broker_enabled=True)
        with TestClient(app) as client:
            resp = client.get("/api/runs/nonexistent")
            self.assertEqual(404, resp.status_code)


class TestBrokerQuestionsEndpoint(unittest.TestCase):
    def test_post_question_run_not_found(self) -> None:
        app = create_app(config_path=_TEST_CONFIG, broker_enabled=True)
        with TestClient(app) as client:
            resp = client.post(
                "/api/runs/nonexistent/questions",
                json={"question": "test?"},
            )
            self.assertEqual(404, resp.status_code)

    def test_get_question_not_found(self) -> None:
        app = create_app(config_path=_TEST_CONFIG, broker_enabled=True)
        with TestClient(app) as client:
            resp = client.get("/api/runs/r1/questions/q1")
            self.assertEqual(404, resp.status_code)

    def test_answer_question_not_found(self) -> None:
        app = create_app(config_path=_TEST_CONFIG, broker_enabled=True)
        with TestClient(app) as client:
            resp = client.post(
                "/api/runs/r1/questions/q1/answer",
                json={"answer": "yes"},
            )
            self.assertEqual(404, resp.status_code)


class TestBrokerTriggerEndpoint(unittest.TestCase):
    def test_trigger_unknown_channel(self) -> None:
        app = create_app(config_path=_TEST_CONFIG, broker_enabled=True)
        with TestClient(app) as client:
            resp = client.post("/api/trigger/unknown", json={"prompt": "test"})
            self.assertEqual(404, resp.status_code)

    def test_trigger_verify_wrong_mode(self) -> None:
        app = create_app(config_path=_TEST_CONFIG, broker_enabled=True)
        with TestClient(app) as client:
            resp = client.get("/api/trigger/http?hub.mode=wrong")
            self.assertEqual(404, resp.status_code)


if __name__ == "__main__":
    unittest.main()
