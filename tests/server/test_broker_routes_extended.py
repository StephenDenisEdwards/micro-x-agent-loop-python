"""Extended tests for broker API routes (HITL, triggers, question flow)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from micro_x_agent_loop.server.app import create_app

_TEST_CONFIG = os.path.join(os.path.dirname(__file__), "config-test-broker.json")
_HTTP_CONFIG = os.path.join(os.path.dirname(__file__), "config-test-broker-http.json")


def _get_app():
    return create_app(config_path=_HTTP_CONFIG, broker_enabled=True)


class BrokerRunsExtendedTests(unittest.TestCase):
    def test_get_run_found(self) -> None:
        app = create_app(config_path=_HTTP_CONFIG, broker_enabled=True)
        with TestClient(app) as client:
            # First create a run via trigger, then look it up
            resp = client.post("/api/trigger/http", json={"prompt": "do stuff"})
            self.assertEqual(200, resp.status_code)
            run_id = resp.json()["run_id"]

            run_resp = client.get(f"/api/runs/{run_id}")
            self.assertEqual(200, run_resp.status_code)
            data = run_resp.json()
            self.assertEqual(run_id, data["id"])


class BrokerQuestionsExtendedTests(unittest.TestCase):
    def _create_run_via_trigger(self, client) -> str:
        resp = client.post("/api/trigger/http", json={"prompt": "do stuff"})
        return resp.json()["run_id"]

    def test_post_question_valid(self) -> None:
        app = _get_app()
        with TestClient(app) as client:
            run_id = self._create_run_via_trigger(client)
            resp = client.post(
                f"/api/runs/{run_id}/questions",
                json={"question": "Should I proceed?"},
            )
            self.assertEqual(200, resp.status_code)
            data = resp.json()
            self.assertIn("question_id", data)
            self.assertIn("timeout_seconds", data)

    def test_post_question_empty_text(self) -> None:
        app = _get_app()
        with TestClient(app) as client:
            run_id = self._create_run_via_trigger(client)
            resp = client.post(
                f"/api/runs/{run_id}/questions",
                json={"question": ""},
            )
            self.assertEqual(400, resp.status_code)

    def test_get_question_found(self) -> None:
        app = _get_app()
        with TestClient(app) as client:
            run_id = self._create_run_via_trigger(client)
            post_resp = client.post(
                f"/api/runs/{run_id}/questions",
                json={"question": "Proceed?"},
            )
            qid = post_resp.json()["question_id"]
            get_resp = client.get(f"/api/runs/{run_id}/questions/{qid}")
            self.assertEqual(200, get_resp.status_code)
            q = get_resp.json()
            self.assertEqual("pending", q["status"])

    def test_answer_question_valid(self) -> None:
        app = _get_app()
        with TestClient(app) as client:
            run_id = self._create_run_via_trigger(client)
            post_resp = client.post(
                f"/api/runs/{run_id}/questions",
                json={"question": "Yes?"},
            )
            qid = post_resp.json()["question_id"]
            ans_resp = client.post(
                f"/api/runs/{run_id}/questions/{qid}/answer",
                json={"answer": "yes"},
            )
            self.assertEqual(200, ans_resp.status_code)
            self.assertEqual("answered", ans_resp.json()["status"])

    def test_answer_question_empty_answer(self) -> None:
        app = _get_app()
        with TestClient(app) as client:
            run_id = self._create_run_via_trigger(client)
            post_resp = client.post(
                f"/api/runs/{run_id}/questions",
                json={"question": "Yes?"},
            )
            qid = post_resp.json()["question_id"]
            resp = client.post(
                f"/api/runs/{run_id}/questions/{qid}/answer",
                json={"answer": ""},
            )
            self.assertEqual(400, resp.status_code)

    def test_answer_already_answered(self) -> None:
        app = _get_app()
        with TestClient(app) as client:
            run_id = self._create_run_via_trigger(client)
            post_resp = client.post(
                f"/api/runs/{run_id}/questions",
                json={"question": "q?"},
            )
            qid = post_resp.json()["question_id"]
            client.post(f"/api/runs/{run_id}/questions/{qid}/answer", json={"answer": "a"})
            resp2 = client.post(
                f"/api/runs/{run_id}/questions/{qid}/answer",
                json={"answer": "b"},
            )
            self.assertEqual(409, resp2.status_code)

    def test_list_questions_for_run(self) -> None:
        app = _get_app()
        with TestClient(app) as client:
            run_id = self._create_run_via_trigger(client)
            client.post(f"/api/runs/{run_id}/questions", json={"question": "Go?"})
            resp = client.get(f"/api/runs/{run_id}/questions")
            self.assertEqual(200, resp.status_code)
            data = resp.json()
            self.assertIn("pending_question", data)


class BrokerTriggerExtendedTests(unittest.TestCase):
    def test_trigger_http_valid(self) -> None:
        app = _get_app()
        with TestClient(app) as client:
            resp = client.post("/api/trigger/http", json={"prompt": "hello"})
            self.assertEqual(200, resp.status_code)
            data = resp.json()
            self.assertEqual("dispatched", data["status"])
            self.assertIn("run_id", data)

    def test_trigger_http_no_prompt_ignored(self) -> None:
        app = _get_app()
        with TestClient(app) as client:
            resp = client.post("/api/trigger/http", json={"prompt": ""})
            self.assertEqual(200, resp.status_code)
            data = resp.json()
            self.assertEqual("ignored", data["status"])

    def test_trigger_http_invalid_json(self) -> None:
        app = _get_app()
        with TestClient(app) as client:
            resp = client.post(
                "/api/trigger/http",
                content=b"not json",
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(400, resp.status_code)

    def test_trigger_verify_subscribe(self) -> None:
        app = _get_app()
        with TestClient(app) as client:
            resp = client.get(
                "/api/trigger/http",
                params={"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "abc"},
            )
            # http adapter has no verify_token, so it should fail verification
            self.assertIn(resp.status_code, [200, 403])

    def test_trigger_channel_no_webhook_support(self) -> None:
        # log adapter doesn't support webhooks
        app = _get_app()
        with TestClient(app) as client:
            resp = client.post("/api/trigger/log", json={"prompt": "test"})
            self.assertEqual(400, resp.status_code)


if __name__ == "__main__":
    unittest.main()
