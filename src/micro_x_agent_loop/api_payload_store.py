"""In-memory ring buffer for API request/response payloads."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from micro_x_agent_loop.usage import UsageResult


@dataclass
class ApiPayload:
    timestamp: float
    model: str
    system_prompt: str
    messages: list[dict]
    tools_count: int
    response_message: dict | None
    stop_reason: str
    usage: UsageResult | None


class ApiPayloadStore:
    """Fixed-size ring buffer of recent API payloads."""

    def __init__(self, max_size: int = 50) -> None:
        self._max_size = max_size
        self._buf: deque[ApiPayload] = deque(maxlen=max_size)

    def record(self, payload: ApiPayload) -> None:
        self._buf.append(payload)

    def get(self, index: int = 0) -> ApiPayload | None:
        """Return a payload by reverse index (0 = most recent)."""
        if not self._buf or index < 0 or index >= len(self._buf):
            return None
        return self._buf[-(index + 1)]

    def __len__(self) -> int:
        return len(self._buf)
