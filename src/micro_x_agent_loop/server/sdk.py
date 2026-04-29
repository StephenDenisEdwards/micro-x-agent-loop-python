"""Python client SDK for the micro-x-agent API server.

Provides both synchronous (REST) and streaming (WebSocket) access to the
agent API.  Designed for integration into scripts, notebooks, and apps.

Example — simple chat::

    from micro_x_agent_loop.server.sdk import AgentClient

    async with AgentClient("http://localhost:8321") as client:
        reply = await client.chat("What is 2+2?")
        print(reply.text)

Example — streaming::

    async with AgentClient("http://localhost:8321") as client:
        async with client.stream("Explain quicksort") as stream:
            async for event in stream:
                if event["type"] == "text_delta":
                    print(event["text"], end="", flush=True)
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChatResponse:
    """Response from a non-streaming chat request."""

    session_id: str
    text: str
    errors: list[str] | None = None


@dataclass(frozen=True)
class HealthStatus:
    """Server health information."""

    status: str
    active_sessions: int
    tools: int
    memory_enabled: bool
    broker: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionInfo:
    """Session metadata."""

    session_id: str
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Streaming context
# ---------------------------------------------------------------------------


class StreamSession:
    """Async iterator over WebSocket events from a single turn.

    Used as an async context manager returned by :meth:`AgentClient.stream`.
    Yields JSON dicts for each server frame (``text_delta``, ``tool_started``,
    ``turn_complete``, ``question``, etc.).

    Call :meth:`answer` to respond to ``question`` events.
    """

    def __init__(self, ws: Any, session_id: str) -> None:
        self._ws = ws
        self.session_id = session_id
        self._done = False

    async def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        async for raw_msg in self._ws:
            data = json.loads(raw_msg)
            yield data
            if data.get("type") in ("turn_complete", "error"):
                self._done = True
                return

    async def send_message(self, text: str) -> None:
        """Send a follow-up message in this session."""
        await self._ws.send(json.dumps({"type": "message", "text": text}))

    async def answer(self, question_id: str, text: str) -> None:
        """Answer a HITL question."""
        await self._ws.send(
            json.dumps(
                {
                    "type": "answer",
                    "question_id": question_id,
                    "text": text,
                }
            )
        )

    async def ping(self) -> None:
        """Send a keepalive ping."""
        await self._ws.send(json.dumps({"type": "ping"}))


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class AgentClient:
    """Async client for the micro-x-agent API server.

    Parameters
    ----------
    base_url:
        Server URL, e.g. ``"http://localhost:8321"``.
    api_secret:
        Optional Bearer token for authentication.
    timeout:
        HTTP request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_secret: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_secret = api_secret
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> AgentClient:
        headers: dict[str, str] = {}
        if self._api_secret:
            headers["Authorization"] = f"Bearer {self._api_secret}"
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=self._timeout,
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    @property
    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            raise RuntimeError("AgentClient must be used as an async context manager")
        return self._http

    # -- Health ---------------------------------------------------------------

    async def health(self) -> HealthStatus:
        """Check server health."""
        resp = await self._client.get("/api/health")
        resp.raise_for_status()
        data = resp.json()
        return HealthStatus(
            status=data["status"],
            active_sessions=data.get("active_sessions", 0),
            tools=data.get("tools", 0),
            memory_enabled=data.get("memory_enabled", False),
            broker=data.get("broker"),
            raw=data,
        )

    # -- Sessions -------------------------------------------------------------

    async def create_session(self) -> SessionInfo:
        """Create a new session."""
        resp = await self._client.post("/api/sessions")
        resp.raise_for_status()
        data = resp.json()
        return SessionInfo(session_id=data["session_id"], raw=data)

    async def list_sessions(self) -> list[dict[str, Any]]:
        """List available sessions."""
        resp = await self._client.get("/api/sessions")
        resp.raise_for_status()
        result: list[dict[str, Any]] = resp.json().get("sessions", [])
        return result

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get session details. Returns None if not found."""
        resp = await self._client.get(f"/api/sessions/{session_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        resp = await self._client.delete(f"/api/sessions/{session_id}")
        resp.raise_for_status()
        return True

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Get message history for a session."""
        resp = await self._client.get(f"/api/sessions/{session_id}/messages")
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        result: list[dict[str, Any]] = resp.json().get("messages", [])
        return result

    # -- Chat (non-streaming) -------------------------------------------------

    async def chat(
        self,
        message: str,
        *,
        session_id: str | None = None,
    ) -> ChatResponse:
        """Send a message and get the complete response.

        If ``session_id`` is not provided, the server creates one automatically.
        """
        payload: dict[str, str] = {"message": message}
        if session_id:
            payload["session_id"] = session_id

        resp = await self._client.post("/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return ChatResponse(
            session_id=data["session_id"],
            text=data.get("response", ""),
            errors=data.get("errors"),
        )

    # -- Streaming (WebSocket) ------------------------------------------------

    @asynccontextmanager
    async def stream(
        self,
        message: str,
        *,
        session_id: str | None = None,
    ) -> AsyncIterator[StreamSession]:
        """Open a WebSocket connection and send a message for streaming.

        Yields a :class:`StreamSession` that can be iterated for events::

            async with client.stream("Hello") as stream:
                async for event in stream:
                    if event["type"] == "text_delta":
                        print(event["text"], end="")
        """
        try:
            import websockets
        except ImportError as exc:
            raise ImportError(
                "The 'websockets' package is required for streaming. Install with: pip install websockets"
            ) from exc

        if not session_id:
            session_id = str(uuid.uuid4())

        ws_scheme = "wss" if self._base_url.startswith("https") else "ws"
        ws_url = self._base_url.replace("https://", f"{ws_scheme}://").replace("http://", f"{ws_scheme}://")
        ws_url = f"{ws_url}/api/ws/{session_id}"

        extra_headers = []
        if self._api_secret:
            extra_headers.append(("Authorization", f"Bearer {self._api_secret}"))

        async with websockets.connect(ws_url, additional_headers=extra_headers or None) as ws:
            session = StreamSession(ws, session_id)
            await ws.send(json.dumps({"type": "message", "text": message}))
            yield session

    # -- Broker ---------------------------------------------------------------

    async def list_jobs(self) -> list[dict[str, Any]]:
        """List broker jobs (requires broker enabled)."""
        resp = await self._client.get("/api/jobs")
        resp.raise_for_status()
        result: list[dict[str, Any]] = resp.json()
        return result
