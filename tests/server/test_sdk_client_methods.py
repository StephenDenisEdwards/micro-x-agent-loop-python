"""Tests for AgentClient REST methods using httpx mock transport."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import MagicMock

import httpx

from micro_x_agent_loop.server.sdk import AgentClient, StreamSession


def _make_response(status_code: int, data: dict | list) -> httpx.Response:
    """Build a fake httpx.Response."""
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(data).encode(),
        headers={"content-type": "application/json"},
    )


class FakeTransport(httpx.AsyncBaseTransport):
    """Simple mock transport that returns pre-configured responses."""

    def __init__(self, responses: dict[tuple[str, str], httpx.Response]) -> None:
        # responses keyed by (method, path)
        self._responses = responses

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        if key in self._responses:
            return self._responses[key]
        return httpx.Response(404, content=b'{"error": "Not found"}')


def _make_client(responses: dict[tuple[str, str], httpx.Response]) -> AgentClient:
    """Return an AgentClient backed by FakeTransport."""
    client = AgentClient("http://test")
    client._http = httpx.AsyncClient(
        transport=FakeTransport(responses),
        base_url="http://test",
    )
    return client


class AgentClientHealthTests(unittest.TestCase):
    def test_health(self) -> None:
        async def go():
            resp = _make_response(200, {
                "status": "ok",
                "active_sessions": 3,
                "tools": 10,
                "memory_enabled": True,
                "broker": {"jobs": 0},
            })
            client = _make_client({("GET", "/api/health"): resp})
            h = await client.health()
            self.assertEqual("ok", h.status)
            self.assertEqual(3, h.active_sessions)
            self.assertEqual(10, h.tools)
            self.assertTrue(h.memory_enabled)
            self.assertIsNotNone(h.broker)
            await client._http.aclose()

        asyncio.run(go())

    def test_health_minimal_response(self) -> None:
        async def go():
            resp = _make_response(200, {"status": "ok"})
            client = _make_client({("GET", "/api/health"): resp})
            h = await client.health()
            self.assertEqual(0, h.active_sessions)
            self.assertFalse(h.memory_enabled)
            await client._http.aclose()

        asyncio.run(go())


class AgentClientSessionTests(unittest.TestCase):
    def test_create_session(self) -> None:
        async def go():
            resp = _make_response(200, {"session_id": "abc123", "status": "created"})
            client = _make_client({("POST", "/api/sessions"): resp})
            s = await client.create_session()
            self.assertEqual("abc123", s.session_id)
            await client._http.aclose()

        asyncio.run(go())

    def test_list_sessions(self) -> None:
        async def go():
            resp = _make_response(200, {"sessions": [{"id": "s1"}, {"id": "s2"}]})
            client = _make_client({("GET", "/api/sessions"): resp})
            sessions = await client.list_sessions()
            self.assertEqual(2, len(sessions))
            await client._http.aclose()

        asyncio.run(go())

    def test_get_session_found(self) -> None:
        async def go():
            resp = _make_response(200, {"id": "s1", "title": "my session"})
            client = _make_client({("GET", "/api/sessions/s1"): resp})
            s = await client.get_session("s1")
            self.assertIsNotNone(s)
            self.assertEqual("s1", s["id"])
            await client._http.aclose()

        asyncio.run(go())

    def test_get_session_not_found(self) -> None:
        async def go():
            resp = _make_response(404, {"error": "not found"})
            client = _make_client({("GET", "/api/sessions/bad"): resp})
            s = await client.get_session("bad")
            self.assertIsNone(s)
            await client._http.aclose()

        asyncio.run(go())

    def test_delete_session(self) -> None:
        async def go():
            resp = _make_response(200, {"status": "deleted"})
            client = _make_client({("DELETE", "/api/sessions/s1"): resp})
            result = await client.delete_session("s1")
            self.assertTrue(result)
            await client._http.aclose()

        asyncio.run(go())

    def test_get_messages_not_found(self) -> None:
        async def go():
            resp = _make_response(404, {"error": "not found"})
            client = _make_client({("GET", "/api/sessions/s1/messages"): resp})
            msgs = await client.get_messages("s1")
            self.assertEqual([], msgs)
            await client._http.aclose()

        asyncio.run(go())

    def test_get_messages_found(self) -> None:
        async def go():
            resp = _make_response(200, {"messages": [{"role": "user", "content": "hi"}]})
            client = _make_client({("GET", "/api/sessions/s1/messages"): resp})
            msgs = await client.get_messages("s1")
            self.assertEqual(1, len(msgs))
            await client._http.aclose()

        asyncio.run(go())


class AgentClientChatTests(unittest.TestCase):
    def test_chat_basic(self) -> None:
        async def go():
            resp = _make_response(200, {
                "session_id": "s1",
                "response": "Hello!",
                "errors": None,
            })
            client = _make_client({("POST", "/api/chat"): resp})
            result = await client.chat("hi")
            self.assertEqual("s1", result.session_id)
            self.assertEqual("Hello!", result.text)
            await client._http.aclose()

        asyncio.run(go())

    def test_chat_with_session_id(self) -> None:
        async def go():
            resp = _make_response(200, {
                "session_id": "s1",
                "response": "reply",
            })
            client = _make_client({("POST", "/api/chat"): resp})
            result = await client.chat("hi", session_id="s1")
            self.assertEqual("s1", result.session_id)
            await client._http.aclose()

        asyncio.run(go())

    def test_chat_errors_included(self) -> None:
        async def go():
            resp = _make_response(200, {
                "session_id": "s2",
                "response": "",
                "errors": ["something went wrong"],
            })
            client = _make_client({("POST", "/api/chat"): resp})
            result = await client.chat("fail")
            self.assertEqual(["something went wrong"], result.errors)
            await client._http.aclose()

        asyncio.run(go())


class AgentClientListJobsTests(unittest.TestCase):
    def test_list_jobs(self) -> None:
        async def go():
            resp = _make_response(200, [{"id": "j1"}, {"id": "j2"}])
            client = _make_client({("GET", "/api/jobs"): resp})
            jobs = await client.list_jobs()
            self.assertEqual(2, len(jobs))
            await client._http.aclose()

        asyncio.run(go())


class AgentClientContextManagerTests(unittest.TestCase):
    def test_context_manager_creates_and_closes(self) -> None:
        async def go():
            async with AgentClient("http://localhost:9999") as client:
                self.assertIsNotNone(client._http)
            # After exit, _http should be None
            self.assertIsNone(client._http)

        asyncio.run(go())

    def test_client_without_context_raises(self) -> None:
        client = AgentClient("http://localhost:9999")
        with self.assertRaises(RuntimeError):
            _ = client._client


class StreamSessionIterTests(unittest.TestCase):
    def test_iter_yields_events_until_turn_complete(self) -> None:
        events = [
            json.dumps({"type": "text_delta", "text": "hi"}),
            json.dumps({"type": "turn_complete"}),
            json.dumps({"type": "text_delta", "text": "ignored"}),
        ]
        collected: list[dict] = []

        async def go():
            ws = MagicMock()

            async def fake_aiter():
                for e in events:
                    yield e

            ws.__aiter__ = lambda self_: fake_aiter()
            session = StreamSession(ws, "s1")
            async for event in session:
                collected.append(event)

        asyncio.run(go())
        self.assertEqual(2, len(collected))
        self.assertEqual("text_delta", collected[0]["type"])
        self.assertEqual("turn_complete", collected[1]["type"])

    def test_iter_stops_on_error(self) -> None:
        events = [
            json.dumps({"type": "error", "message": "boom"}),
        ]
        collected: list[dict] = []

        async def go():
            ws = MagicMock()

            async def fake_aiter():
                for e in events:
                    yield e

            ws.__aiter__ = lambda self_: fake_aiter()
            session = StreamSession(ws, "s1")
            async for event in session:
                collected.append(event)

        asyncio.run(go())
        self.assertEqual(1, len(collected))
        self.assertEqual("error", collected[0]["type"])


if __name__ == "__main__":
    unittest.main()
