"""Tests for the broker webhook server endpoints using FastAPI TestClient."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

from micro_x_agent_loop.broker.webhook_server import WebhookServer


def _make_server(
    *,
    store: Any = None,
    dispatcher: Any = None,
    adapters: dict | None = None,
    api_secret: str | None = None,
) -> WebhookServer:
    if store is None:
        store = MagicMock()
        store.list_jobs.return_value = [
            {"id": "j1", "enabled": True},
            {"id": "j2", "enabled": False},
        ]
    if dispatcher is None:
        dispatcher = MagicMock()
        dispatcher.active_run_count = 0
        dispatcher.at_capacity = False
    if adapters is None:
        adapters = {}
    return WebhookServer(
        store, dispatcher, adapters,
        host="127.0.0.1", port=9999,
        api_secret=api_secret,
    )


def _client(server: WebhookServer):
    from fastapi.testclient import TestClient
    return TestClient(server._app)


class HealthEndpointTests(unittest.TestCase):
    def test_health_returns_ok(self) -> None:
        server = _make_server()
        client = _client(server)
        resp = client.get("/api/health")
        self.assertEqual(200, resp.status_code)
        data = resp.json()
        self.assertEqual("ok", data["status"])
        self.assertEqual(2, data["jobs_total"])
        self.assertEqual(1, data["jobs_enabled"])

    def test_health_no_auth_required(self) -> None:
        server = _make_server(api_secret="secret123")
        client = _client(server)
        resp = client.get("/api/health")
        self.assertEqual(200, resp.status_code)


class AuthMiddlewareTests(unittest.TestCase):
    def test_protected_endpoint_requires_auth(self) -> None:
        server = _make_server(api_secret="secret123")
        client = _client(server)
        resp = client.get("/api/jobs")
        self.assertEqual(401, resp.status_code)

    def test_protected_endpoint_with_valid_token(self) -> None:
        server = _make_server(api_secret="secret123")
        client = _client(server)
        resp = client.get("/api/jobs", headers={"Authorization": "Bearer secret123"})
        self.assertEqual(200, resp.status_code)

    def test_no_auth_when_no_secret(self) -> None:
        server = _make_server(api_secret=None)
        client = _client(server)
        resp = client.get("/api/jobs")
        self.assertEqual(200, resp.status_code)


class JobsEndpointTests(unittest.TestCase):
    def test_list_jobs(self) -> None:
        server = _make_server()
        client = _client(server)
        resp = client.get("/api/jobs")
        self.assertEqual(200, resp.status_code)
        self.assertEqual(2, len(resp.json()))


class RunsEndpointTests(unittest.TestCase):
    def test_get_run_found(self) -> None:
        store = MagicMock()
        store.list_jobs.return_value = []
        store.get_run.return_value = {"id": "r1", "status": "completed"}
        server = _make_server(store=store)
        client = _client(server)
        resp = client.get("/api/runs/r1")
        self.assertEqual(200, resp.status_code)
        self.assertEqual("r1", resp.json()["id"])

    def test_get_run_not_found(self) -> None:
        store = MagicMock()
        store.list_jobs.return_value = []
        store.get_run.return_value = None
        server = _make_server(store=store)
        client = _client(server)
        resp = client.get("/api/runs/nope")
        self.assertEqual(404, resp.status_code)


class QuestionEndpointTests(unittest.TestCase):
    def _store(self) -> MagicMock:
        store = MagicMock()
        store.list_jobs.return_value = []
        store.get_run.return_value = {"id": "r1", "job_id": "j1"}
        store.get_job.return_value = {"hitl_timeout_seconds": 60}
        store.create_question.return_value = "q1"
        return store

    def test_post_question(self) -> None:
        store = self._store()
        server = _make_server(store=store)
        client = _client(server)
        resp = client.post("/api/runs/r1/questions", json={"question": "What color?"})
        self.assertEqual(200, resp.status_code)
        self.assertEqual("q1", resp.json()["question_id"])
        store.create_question.assert_called_once()

    def test_post_question_empty_text(self) -> None:
        store = self._store()
        server = _make_server(store=store)
        client = _client(server)
        resp = client.post("/api/runs/r1/questions", json={"question": ""})
        self.assertEqual(400, resp.status_code)

    def test_post_question_run_not_found(self) -> None:
        store = MagicMock()
        store.list_jobs.return_value = []
        store.get_run.return_value = None
        server = _make_server(store=store)
        client = _client(server)
        resp = client.post("/api/runs/r1/questions", json={"question": "test"})
        self.assertEqual(404, resp.status_code)

    def test_post_question_invalid_json(self) -> None:
        store = self._store()
        server = _make_server(store=store)
        client = _client(server)
        resp = client.post(
            "/api/runs/r1/questions",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(400, resp.status_code)

    def test_get_question(self) -> None:
        store = MagicMock()
        store.list_jobs.return_value = []
        store.get_question.return_value = {"id": "q1", "run_id": "r1", "status": "pending"}
        server = _make_server(store=store)
        client = _client(server)
        resp = client.get("/api/runs/r1/questions/q1")
        self.assertEqual(200, resp.status_code)

    def test_get_question_not_found(self) -> None:
        store = MagicMock()
        store.list_jobs.return_value = []
        store.get_question.return_value = None
        server = _make_server(store=store)
        client = _client(server)
        resp = client.get("/api/runs/r1/questions/q1")
        self.assertEqual(404, resp.status_code)

    def test_get_question_wrong_run(self) -> None:
        store = MagicMock()
        store.list_jobs.return_value = []
        store.get_question.return_value = {"id": "q1", "run_id": "other", "status": "pending"}
        server = _make_server(store=store)
        client = _client(server)
        resp = client.get("/api/runs/r1/questions/q1")
        self.assertEqual(404, resp.status_code)


class AnswerQuestionEndpointTests(unittest.TestCase):
    def test_answer_question(self) -> None:
        store = MagicMock()
        store.list_jobs.return_value = []
        store.get_question.return_value = {"id": "q1", "run_id": "r1", "status": "pending"}
        store.answer_question.return_value = True
        server = _make_server(store=store)
        client = _client(server)
        resp = client.post("/api/runs/r1/questions/q1/answer", json={"answer": "blue"})
        self.assertEqual(200, resp.status_code)
        self.assertEqual("answered", resp.json()["status"])

    def test_answer_already_answered(self) -> None:
        store = MagicMock()
        store.list_jobs.return_value = []
        store.get_question.return_value = {"id": "q1", "run_id": "r1", "status": "answered"}
        server = _make_server(store=store)
        client = _client(server)
        resp = client.post("/api/runs/r1/questions/q1/answer", json={"answer": "blue"})
        self.assertEqual(409, resp.status_code)

    def test_answer_empty_text(self) -> None:
        store = MagicMock()
        store.list_jobs.return_value = []
        store.get_question.return_value = {"id": "q1", "run_id": "r1", "status": "pending"}
        server = _make_server(store=store)
        client = _client(server)
        resp = client.post("/api/runs/r1/questions/q1/answer", json={"answer": ""})
        self.assertEqual(400, resp.status_code)

    def test_answer_not_found(self) -> None:
        store = MagicMock()
        store.list_jobs.return_value = []
        store.get_question.return_value = None
        server = _make_server(store=store)
        client = _client(server)
        resp = client.post("/api/runs/r1/questions/q1/answer", json={"answer": "x"})
        self.assertEqual(404, resp.status_code)


class PendingQuestionsEndpointTests(unittest.TestCase):
    def test_list_pending(self) -> None:
        store = MagicMock()
        store.list_jobs.return_value = []
        store.get_pending_question.return_value = {"id": "q1", "question": "test"}
        server = _make_server(store=store)
        client = _client(server)
        resp = client.get("/api/runs/r1/questions")
        self.assertEqual(200, resp.status_code)
        self.assertIn("pending_question", resp.json())


class TriggerVerifyEndpointTests(unittest.TestCase):
    def test_verify_success(self) -> None:
        adapter = MagicMock()
        adapter.verify_token = "my_token"
        server = _make_server(adapters={"whatsapp": adapter})
        client = _client(server)
        resp = client.get(
            "/api/trigger/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "my_token",
                "hub.challenge": "challenge123",
            },
        )
        self.assertEqual(200, resp.status_code)
        self.assertEqual("challenge123", resp.text)

    def test_verify_wrong_token(self) -> None:
        adapter = MagicMock()
        adapter.verify_token = "my_token"
        server = _make_server(adapters={"whatsapp": adapter})
        client = _client(server)
        resp = client.get(
            "/api/trigger/whatsapp",
            params={"hub.mode": "subscribe", "hub.verify_token": "wrong"},
        )
        self.assertEqual(403, resp.status_code)

    def test_verify_unknown_channel(self) -> None:
        server = _make_server(adapters={})
        client = _client(server)
        resp = client.get(
            "/api/trigger/unknown",
            params={"hub.mode": "subscribe", "hub.verify_token": "x"},
        )
        self.assertEqual(404, resp.status_code)

    def test_verify_wrong_mode(self) -> None:
        server = _make_server(adapters={"ch": MagicMock()})
        client = _client(server)
        resp = client.get(
            "/api/trigger/ch",
            params={"hub.mode": "unsubscribe"},
        )
        self.assertEqual(404, resp.status_code)


class TriggerPostEndpointTests(unittest.TestCase):
    def test_trigger_unknown_channel(self) -> None:
        server = _make_server(adapters={})
        client = _client(server)
        resp = client.post("/api/trigger/unknown", json={})
        self.assertEqual(404, resp.status_code)

    def test_trigger_no_webhook_support(self) -> None:
        adapter = MagicMock()
        adapter.supports_webhook = False
        server = _make_server(adapters={"ch": adapter})
        client = _client(server)
        resp = client.post("/api/trigger/ch", json={})
        self.assertEqual(400, resp.status_code)

    def test_trigger_unauthorized(self) -> None:
        adapter = MagicMock()
        adapter.supports_webhook = True
        adapter.verify_request.return_value = False
        server = _make_server(adapters={"ch": adapter})
        client = _client(server)
        resp = client.post("/api/trigger/ch", json={"msg": "hi"})
        self.assertEqual(401, resp.status_code)

    def test_trigger_ignored(self) -> None:
        adapter = MagicMock()
        adapter.supports_webhook = True
        adapter.verify_request.return_value = True
        adapter.parse_webhook.return_value = None
        server = _make_server(adapters={"ch": adapter})
        client = _client(server)
        resp = client.post("/api/trigger/ch", json={"msg": "status_update"})
        self.assertEqual(200, resp.status_code)
        self.assertEqual("ignored", resp.json()["status"])

    def test_trigger_dispatched(self) -> None:
        trigger_req = MagicMock()
        trigger_req.prompt = "hello"
        trigger_req.session_id = None
        trigger_req.config_profile = None
        trigger_req.response_target = ""
        trigger_req.sender_id = "user1"

        adapter = MagicMock()
        adapter.supports_webhook = True
        adapter.verify_request.return_value = True
        adapter.parse_webhook.return_value = trigger_req

        store = MagicMock()
        store.list_jobs.return_value = []
        store.create_run.return_value = "run-1"

        dispatcher = MagicMock()
        dispatcher.active_run_count = 0
        dispatcher.at_capacity = False

        server = _make_server(store=store, dispatcher=dispatcher, adapters={"ch": adapter})
        client = _client(server)
        resp = client.post("/api/trigger/ch", json={"msg": "hi"})
        self.assertEqual(200, resp.status_code)
        self.assertEqual("dispatched", resp.json()["status"])
        dispatcher.dispatch.assert_called_once()

    def test_trigger_at_capacity(self) -> None:
        trigger_req = MagicMock()
        trigger_req.prompt = "hello"
        trigger_req.session_id = None

        adapter = MagicMock()
        adapter.supports_webhook = True
        adapter.verify_request.return_value = True
        adapter.parse_webhook.return_value = trigger_req

        dispatcher = MagicMock()
        dispatcher.active_run_count = 2
        dispatcher.at_capacity = True

        server = _make_server(dispatcher=dispatcher, adapters={"ch": adapter})
        client = _client(server)
        resp = client.post("/api/trigger/ch", json={"msg": "hi"})
        self.assertEqual(503, resp.status_code)


if __name__ == "__main__":
    unittest.main()
