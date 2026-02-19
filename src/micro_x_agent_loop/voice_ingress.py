from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Protocol

from micro_x_agent_loop.tool import Tool


class VoiceIngress(Protocol):
    async def stream_events(self, *, session_id: str, since_seq: int) -> AsyncIterator[dict[str, Any]]: ...


class PollingVoiceIngress:
    def __init__(self, *, tool_map: dict[str, Tool], poll_interval_seconds: float = 0.2):
        self._tool_map = tool_map
        self._poll_interval_seconds = poll_interval_seconds

    async def stream_events(self, *, session_id: str, since_seq: int) -> AsyncIterator[dict[str, Any]]:
        last_seq = since_seq
        updates_tool = next((name for name in self._tool_map if name.endswith("__stt_get_updates")), None)
        if updates_tool is None:
            return

        tool = self._tool_map.get(updates_tool)
        if tool is None:
            return

        while True:
            raw = await tool.execute({"session_id": session_id, "since_seq": last_seq, "limit": 100})
            payload = _parse_json_object(raw)
            events = payload.get("events", []) or []
            for event in events:
                seq = int(event.get("seq", 0))
                if seq > last_seq:
                    last_seq = seq
                yield event
            await asyncio.sleep(self._poll_interval_seconds)


def _parse_json_object(raw: str) -> dict[str, Any]:
    import json

    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        parsed = json.loads(text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("Tool response was not valid JSON object")
