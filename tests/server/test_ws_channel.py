"""Tests for WebSocketChannel."""

from __future__ import annotations

import asyncio
import json
import unittest

from micro_x_agent_loop.server.ws_channel import WebSocketChannel


class FakeWebSocket:
    """Minimal WebSocket fake for testing."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.closed = False

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)

    async def accept(self) -> None:
        pass


class TestWebSocketChannelEmit(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_emit_text_delta(self) -> None:
        ws = FakeWebSocket()
        ch = WebSocketChannel(ws)

        async def go():
            ch.emit_text_delta("Hello")
            await asyncio.sleep(0.05)  # let ensure_future run

        self._run(go())
        self.assertEqual(1, len(ws.sent))
        self.assertEqual({"type": "text_delta", "text": "Hello"}, ws.sent[0])

    def test_emit_tool_started(self) -> None:
        ws = FakeWebSocket()
        ch = WebSocketChannel(ws)

        async def go():
            ch.emit_tool_started("t1", "read_file")
            await asyncio.sleep(0.05)

        self._run(go())
        self.assertEqual(1, len(ws.sent))
        msg = ws.sent[0]
        self.assertEqual("tool_started", msg["type"])
        self.assertEqual("t1", msg["tool_use_id"])
        self.assertEqual("read_file", msg["tool"])

    def test_emit_tool_completed(self) -> None:
        ws = FakeWebSocket()
        ch = WebSocketChannel(ws)

        async def go():
            ch.emit_tool_completed("t1", "read_file", True)
            await asyncio.sleep(0.05)

        self._run(go())
        self.assertEqual(1, len(ws.sent))
        msg = ws.sent[0]
        self.assertEqual("tool_completed", msg["type"])
        self.assertTrue(msg["error"])

    def test_emit_turn_complete(self) -> None:
        ws = FakeWebSocket()
        ch = WebSocketChannel(ws)

        async def go():
            ch.emit_turn_complete({"input_tokens": 100})
            await asyncio.sleep(0.05)

        self._run(go())
        self.assertEqual(1, len(ws.sent))
        self.assertEqual("turn_complete", ws.sent[0]["type"])

    def test_emit_error(self) -> None:
        ws = FakeWebSocket()
        ch = WebSocketChannel(ws)

        async def go():
            ch.emit_error("something broke")
            await asyncio.sleep(0.05)

        self._run(go())
        self.assertEqual(1, len(ws.sent))
        self.assertEqual({"type": "error", "message": "something broke"}, ws.sent[0])


class TestWebSocketChannelAskUser(unittest.TestCase):
    def test_ask_user_receives_answer(self) -> None:
        ws = FakeWebSocket()
        ch = WebSocketChannel(ws, ask_user_timeout=5)

        async def go():
            # Start ask_user in background
            task = asyncio.create_task(ch.ask_user("Which file?"))
            await asyncio.sleep(0.05)  # let question be sent

            # Simulate client answer
            ch.receive_answer("q1", "main.py")
            return await task

        answer = asyncio.run(go())
        self.assertEqual("main.py", answer)
        # Verify question was sent
        self.assertTrue(any(m["type"] == "question" for m in ws.sent))

    def test_ask_user_timeout(self) -> None:
        ws = FakeWebSocket()
        ch = WebSocketChannel(ws, ask_user_timeout=0.1)

        answer = asyncio.run(ch.ask_user("Which file?"))
        self.assertIn("No response from human", answer)

    def test_receive_answer_unknown_question(self) -> None:
        ws = FakeWebSocket()
        ch = WebSocketChannel(ws)
        self.assertFalse(ch.receive_answer("q999", "answer"))


class TestWebSocketChannelAskUserWithOptions(unittest.TestCase):
    def test_ask_user_sends_options(self) -> None:
        ws = FakeWebSocket()
        ch = WebSocketChannel(ws, ask_user_timeout=5)
        options = [{"label": "A", "description": "First"}]

        async def go():
            task = asyncio.create_task(ch.ask_user("Pick one", options))
            await asyncio.sleep(0.05)
            ch.receive_answer("q1", "A")
            return await task

        answer = asyncio.run(go())
        self.assertEqual("A", answer)
        question_msg = next(m for m in ws.sent if m["type"] == "question")
        self.assertEqual(options, question_msg["options"])


if __name__ == "__main__":
    unittest.main()
