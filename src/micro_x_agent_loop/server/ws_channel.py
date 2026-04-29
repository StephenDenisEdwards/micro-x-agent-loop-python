"""WebSocketChannel — AgentChannel implementation for WebSocket clients."""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger
from starlette.websockets import WebSocket, WebSocketDisconnect


class WebSocketChannel:
    """AgentChannel that sends events as JSON frames over a WebSocket.

    Output events (text_delta, tool_started, etc.) are sent immediately.
    ``ask_user`` sends a question frame and waits for an answer frame
    from the client, with a configurable timeout.
    """

    def __init__(self, ws: WebSocket, *, ask_user_timeout: int = 300) -> None:
        self._ws = ws
        self._ask_user_timeout = ask_user_timeout
        self._pending_questions: dict[str, asyncio.Future[str]] = {}
        self._question_counter = 0

    async def _send(self, data: dict[str, Any]) -> None:
        try:
            await self._ws.send_json(data)
        except (WebSocketDisconnect, RuntimeError):
            logger.debug("WebSocket disconnected during send")

    def emit_text_delta(self, text: str) -> None:
        asyncio.ensure_future(self._send({"type": "text_delta", "text": text}))

    def emit_tool_started(self, tool_use_id: str, tool_name: str) -> None:
        asyncio.ensure_future(
            self._send(
                {
                    "type": "tool_started",
                    "tool_use_id": tool_use_id,
                    "tool": tool_name,
                }
            )
        )

    def emit_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None:
        asyncio.ensure_future(
            self._send(
                {
                    "type": "tool_completed",
                    "tool_use_id": tool_use_id,
                    "tool": tool_name,
                    "error": is_error,
                }
            )
        )

    def emit_turn_complete(self, usage: dict[str, Any]) -> None:
        asyncio.ensure_future(
            self._send(
                {
                    "type": "turn_complete",
                    "usage": usage,
                }
            )
        )

    def emit_error(self, message: str) -> None:
        asyncio.ensure_future(
            self._send(
                {
                    "type": "error",
                    "message": message,
                }
            )
        )

    def emit_system_message(self, text: str) -> None:
        asyncio.ensure_future(
            self._send(
                {
                    "type": "system_message",
                    "text": text,
                }
            )
        )

    async def ask_user(self, question: str, options: list[dict[str, str]] | None = None) -> str:
        self._question_counter += 1
        question_id = f"q{self._question_counter}"

        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._pending_questions[question_id] = future

        await self._send(
            {
                "type": "question",
                "id": question_id,
                "text": question,
                "options": options,
            }
        )

        try:
            answer = await asyncio.wait_for(future, timeout=self._ask_user_timeout)
        except TimeoutError:
            answer = (
                "No response from human — question timed out. "
                "Proceed with your best judgement or report that you cannot continue."
            )
        finally:
            self._pending_questions.pop(question_id, None)

        return answer

    def receive_answer(self, question_id: str, answer: str) -> bool:
        """Called by the WebSocket message handler when a client sends an answer.

        Returns True if the answer was delivered, False if the question was not found.
        """
        future = self._pending_questions.get(question_id)
        if future is None or future.done():
            return False
        future.set_result(answer)
        return True
