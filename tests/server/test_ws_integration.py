"""WebSocket integration tests — full message flow through the FastAPI app.

These tests exercise the real WebSocket endpoint with a fake agent,
catching interaction bugs that unit tests miss:
- turn_complete must be sent after agent.run() completes
- HITL answers must flow through while agent.run() is in progress
- ping/pong must work during an active turn
- errors must be surfaced to the client
"""

from __future__ import annotations

import asyncio
import os
import unittest
from typing import Any

from fastapi.testclient import TestClient

from micro_x_agent_loop.server.agent_manager import AgentManager
from micro_x_agent_loop.server.app import create_app

_TEST_CONFIG = os.path.join(os.path.dirname(__file__), "config-test.json")


class FakeAgent:
    """Minimal agent that calls channel methods directly.

    Simulates agent behaviour without LLM calls. The ``run_fn`` callback
    controls what happens during ``run()`` — emit text, call ask_user, etc.
    """

    def __init__(self) -> None:
        self._channel: Any = None
        self._turn_engine = type("E", (), {"_channel": None})()
        self.run_fn: Any = None

    async def run(self, text: str) -> None:
        if self.run_fn:
            await self.run_fn(text, self._channel)

    async def initialize_session(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass


class FakeAgentManager(AgentManager):
    """AgentManager that returns a pre-configured FakeAgent.

    Injected into create_app() via the agent_manager parameter,
    eliminating the need to patch internal state.
    """

    def __init__(self, fake_agent: FakeAgent) -> None:
        self._fake_agent = fake_agent
        self._slots: dict = {}

    async def get_or_create(self, session_id: str, channel: Any = None) -> FakeAgent:  # type: ignore[override]
        self._fake_agent._channel = channel
        self._fake_agent._turn_engine._channel = channel
        return self._fake_agent

    async def destroy(self, session_id: str) -> bool:
        return True

    def list_sessions(self) -> list[dict[str, Any]]:
        return []

    @property
    def active_count(self) -> int:
        return 0

    async def shutdown_all(self) -> None:
        pass


def _create_test_app(fake: FakeAgent) -> Any:
    """Create a test app with a FakeAgentManager injected."""
    return create_app(
        config_path=_TEST_CONFIG,
        agent_manager=FakeAgentManager(fake),
    )


def _collect_events(ws: Any, *, until: str = "turn_complete", max_reads: int = 20) -> list[dict]:
    """Read WebSocket events until the target type or max reads."""
    events = []
    for _ in range(max_reads):
        try:
            data = ws.receive_json(mode="text")
            events.append(data)
            if data.get("type") == until:
                break
        except Exception:
            break
    return events


class TestWebSocketTurnComplete(unittest.TestCase):
    """Verify turn_complete is always sent after agent.run() finishes."""

    def test_simple_message_gets_turn_complete(self) -> None:
        fake = FakeAgent()

        async def simple_run(text: str, channel: Any) -> None:
            channel.emit_text_delta("Hello back")
            await asyncio.sleep(0.01)

        fake.run_fn = simple_run
        app = _create_test_app(fake)

        with TestClient(app) as client:
            with client.websocket_connect("/api/ws/test-turn") as ws:
                ws.send_json({"type": "message", "text": "hello"})
                events = _collect_events(ws)

                types = [e["type"] for e in events]
                self.assertIn("text_delta", types, "Expected text_delta event")
                self.assertIn("turn_complete", types, "Expected turn_complete event")

    def test_agent_error_still_sends_turn_complete(self) -> None:
        fake = FakeAgent()

        async def failing_run(text: str, channel: Any) -> None:
            raise RuntimeError("LLM exploded")

        fake.run_fn = failing_run
        app = _create_test_app(fake)

        with TestClient(app) as client:
            with client.websocket_connect("/api/ws/test-error") as ws:
                ws.send_json({"type": "message", "text": "crash"})
                events = _collect_events(ws)

                types = [e["type"] for e in events]
                self.assertIn("error", types, "Expected error event")
                self.assertIn("turn_complete", types, "turn_complete must be sent even on error")


class TestWebSocketHitl(unittest.TestCase):
    """Verify HITL question/answer flows without deadlock."""

    def test_ask_user_answer_flows_through(self) -> None:
        """The bug: agent.run() was awaited inline, blocking the receive loop.
        answer messages could never be read, causing a deadlock."""
        fake = FakeAgent()
        captured_answer: list[str] = []

        async def hitl_run(text: str, channel: Any) -> None:
            answer = await channel.ask_user(
                "Which format?",
                [
                    {"label": "PDF", "description": "Portable Document Format"},
                    {"label": "HTML", "description": "Web page"},
                ],
            )
            captured_answer.append(answer)
            channel.emit_text_delta(f"Using {answer}")
            await asyncio.sleep(0.01)

        fake.run_fn = hitl_run
        app = _create_test_app(fake)

        with TestClient(app) as client:
            with client.websocket_connect("/api/ws/test-hitl") as ws:
                ws.send_json({"type": "message", "text": "make a report"})

                # Read until we get the question
                question_msg = None
                for _ in range(20):
                    try:
                        data = ws.receive_json(mode="text")
                        if data.get("type") == "question":
                            question_msg = data
                            break
                    except Exception:
                        break

                self.assertIsNotNone(question_msg, "Expected question event from ask_user")
                self.assertEqual("Which format?", question_msg["text"])
                self.assertEqual(2, len(question_msg["options"]))

                # Send answer
                ws.send_json(
                    {
                        "type": "answer",
                        "question_id": question_msg["id"],
                        "text": "PDF",
                    }
                )

                events = _collect_events(ws)
                types = [e["type"] for e in events]
                self.assertIn("text_delta", types, "Expected text after answer")
                self.assertIn("turn_complete", types, "Expected turn_complete after HITL")
                self.assertEqual(["PDF"], captured_answer, "Agent should have received the answer")


class TestWebSocketPing(unittest.TestCase):
    """Verify ping/pong works, including during an active turn."""

    def test_ping_pong(self) -> None:
        app = create_app(config_path=_TEST_CONFIG)
        with TestClient(app) as client:
            with client.websocket_connect("/api/ws/test-ping") as ws:
                ws.send_json({"type": "ping"})
                data = ws.receive_json(mode="text")
                self.assertEqual("pong", data["type"])

    def test_ping_during_active_turn(self) -> None:
        """Ping must work while agent.run() is in progress."""
        fake = FakeAgent()

        async def slow_run(text: str, channel: Any) -> None:
            await asyncio.sleep(2.0)
            channel.emit_text_delta("Done")

        fake.run_fn = slow_run
        app = _create_test_app(fake)

        with TestClient(app) as client:
            with client.websocket_connect("/api/ws/test-ping-during") as ws:
                ws.send_json({"type": "message", "text": "slow task"})

                import time

                time.sleep(0.1)

                ws.send_json({"type": "ping"})
                data = ws.receive_json(mode="text")
                self.assertEqual("pong", data["type"])


class TestWebSocketLifecycle(unittest.TestCase):
    """Verify clean startup and shutdown."""

    def test_app_starts_and_stops_cleanly(self) -> None:
        app = create_app(config_path=_TEST_CONFIG)
        with TestClient(app) as client:
            resp = client.get("/api/health")
            self.assertEqual(200, resp.status_code)


if __name__ == "__main__":
    unittest.main()
