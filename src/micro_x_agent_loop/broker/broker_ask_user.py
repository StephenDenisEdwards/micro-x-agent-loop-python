"""Broker-aware ask_user handler for async human-in-the-loop in subprocess runs."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger

from micro_x_agent_loop.ask_user import ASK_USER_SCHEMA


class BrokerAskUserHandler:
    """Replaces AskUserHandler in broker subprocess runs.

    Posts questions to the broker HTTP API and polls for answers.
    The broker routes questions to the originating channel adapter.
    """

    def __init__(
        self,
        broker_url: str,
        run_id: str,
        *,
        timeout: int = 300,
        poll_interval: int = 3,
    ) -> None:
        self._broker_url = broker_url.rstrip("/")
        self._run_id = run_id
        self._timeout = timeout
        self._poll_interval = poll_interval

    @staticmethod
    def get_schema() -> dict[str, Any]:
        return ASK_USER_SCHEMA

    @staticmethod
    def is_ask_user_call(tool_name: str) -> bool:
        return tool_name == "ask_user"

    async def handle(self, tool_input: dict[str, Any]) -> str:
        """Post question to broker and poll for answer."""
        import httpx

        question = tool_input.get("question", "")
        options = tool_input.get("options")

        payload: dict[str, Any] = {"question": question}
        if options:
            payload["options"] = options

        async with httpx.AsyncClient(timeout=10) as client:
            # Post question to broker
            url = f"{self._broker_url}/api/runs/{self._run_id}/questions"
            try:
                resp = await client.post(url, json=payload)
                if not resp.is_success:
                    logger.warning(f"Failed to post HITL question: HTTP {resp.status_code}")
                    return json.dumps({"answer": _NO_RESPONSE_MSG})
                data = resp.json()
                question_id = data["question_id"]
            except Exception as ex:
                logger.warning(f"Failed to reach broker for HITL question: {ex}")
                return json.dumps({"answer": _NO_RESPONSE_MSG})

            logger.info(f"HITL question posted: id={question_id}, timeout={self._timeout}s")

            # Poll for answer
            poll_url = f"{self._broker_url}/api/runs/{self._run_id}/questions/{question_id}"
            elapsed = 0
            while elapsed < self._timeout:
                await asyncio.sleep(self._poll_interval)
                elapsed += self._poll_interval
                try:
                    resp = await client.get(poll_url)
                    if not resp.is_success:
                        continue
                    data = resp.json()
                    if data["status"] == "answered":
                        logger.info(f"HITL answer received for question {question_id}")
                        return json.dumps({"answer": data["answer"]})
                    if data["status"] == "timed_out":
                        logger.info(f"HITL question {question_id} timed out")
                        break
                except Exception:
                    continue

        return json.dumps({"answer": _NO_RESPONSE_MSG})


_NO_RESPONSE_MSG = (
    "No response from human — question timed out. "
    "Proceed with your best judgement or report that you cannot continue."
)
