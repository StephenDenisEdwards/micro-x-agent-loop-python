"""Shared test fakes used across the test suite."""

from __future__ import annotations

from typing import Any

from micro_x_agent_loop.tool import ToolResult
from micro_x_agent_loop.usage import UsageResult

# ---------------------------------------------------------------------------
# Anthropic stream fakes
# ---------------------------------------------------------------------------


class FakeStreamContext:
    def __init__(self, events: list[object], final_message: object):
        self._events = events
        self._final_message = final_message

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def __aiter__(self):
        self._iter = iter(self._events)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def get_final_message(self):
        return self._final_message


class FakeMessages:
    def __init__(self, stream_ctx=None, create_response=None):
        self._stream_ctx = stream_ctx
        self._create_response = create_response

    def stream(self, **kwargs):
        return self._stream_ctx

    async def create(self, **kwargs):
        return self._create_response


class FakeAnthropicClient:
    def __init__(self, stream_ctx=None, create_response=None):
        self.messages = FakeMessages(stream_ctx, create_response)


# ---------------------------------------------------------------------------
# Tool fakes
# ---------------------------------------------------------------------------


class FakeTool:
    """Configurable fake that satisfies the ``Tool`` protocol."""

    def __init__(
        self,
        name: str = "noop",
        description: str = "noop",
        input_schema: dict[str, Any] | None = None,
        execute_result: str = "ok",
        execute_side_effect: Exception | None = None,
        is_mutating: bool = False,
        touched_paths: list[str] | None = None,
    ):
        self._name = name
        self._description = description
        self._input_schema = input_schema or {"type": "object"}
        self._execute_result = execute_result
        self._execute_side_effect = execute_side_effect
        self._is_mutating = is_mutating
        self._touched_paths = touched_paths or []
        self.execute_calls: int = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    @property
    def is_mutating(self) -> bool:
        return self._is_mutating

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]:
        return self._touched_paths

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult:
        self.execute_calls += 1
        if self._execute_side_effect is not None:
            raise self._execute_side_effect
        return ToolResult(text=self._execute_result)


class FakeMcpTool(FakeTool):
    """FakeTool with output_schema, simulating an McpToolProxy."""

    def __init__(
        self,
        *,
        name: str = "server__tool",
        description: str = "mcp tool",
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        is_mutating: bool = False,
    ):
        super().__init__(
            name=name,
            description=description,
            input_schema=input_schema,
            is_mutating=is_mutating,
        )
        self._output_schema = output_schema

    @property
    def output_schema(self) -> dict[str, Any] | None:
        return self._output_schema


# ---------------------------------------------------------------------------
# Provider fake
# ---------------------------------------------------------------------------


class FakeProvider:
    """Records ``create_message`` calls and returns queued responses."""

    def __init__(self, summary_text: str = "summary text", model: str = "m") -> None:
        self.calls: list[dict] = []
        self._summary_text = summary_text
        self._model = model

    async def create_message(self, model, max_tokens, temperature, messages):
        self.calls.append({
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        })
        return self._summary_text, UsageResult(input_tokens=100, output_tokens=50, model=model)


class FakeStreamProvider:
    """Provider fake with queued ``stream_chat`` responses for TurnEngine tests."""

    def __init__(self, responses: list[tuple] | None = None) -> None:
        self.responses: list[tuple] = list(responses or [])
        self.stream_calls: list[dict] = []

    def queue(
        self,
        text: str = "",
        tool_use_blocks: list[dict] | None = None,
        stop_reason: str = "end_turn",
        usage: UsageResult | None = None,
    ) -> None:
        message = {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        }
        self.responses.append((
            message,
            tool_use_blocks or [],
            stop_reason,
            usage or UsageResult(input_tokens=10, output_tokens=5, model="m"),
        ))

    async def stream_chat(self, model, max_tokens, temperature, system_prompt, messages, tools, **kwargs):
        self.stream_calls.append({
            "model": model,
            "max_tokens": max_tokens,
            "messages": list(messages),
        })
        return self.responses.pop(0)

    def convert_tools(self, tools):
        return [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools]


# ---------------------------------------------------------------------------
# Event emitter fake
# ---------------------------------------------------------------------------


class FakeEventEmitter:
    """No-op event emitter that records calls."""

    def __init__(self) -> None:
        self.events: list[tuple] = []

    def emit(self, *args: Any, **kwargs: Any) -> None:
        self.events.append((args, kwargs))


# ---------------------------------------------------------------------------
# Session / checkpoint manager fakes
# ---------------------------------------------------------------------------


class SessionManagerFake:
    """In-memory session manager for command-level tests."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {
            "s1": {
                "id": "s1",
                "title": "Session One",
                "parent_session_id": None,
                "created_at": "2026-02-19T00:00:00+00:00",
                "updated_at": "2026-02-19T00:00:00+00:00",
                "status": "active",
            }
        }
        self._messages: dict[str, list[dict]] = {"s1": []}

    def load_messages(self, session_id: str) -> list[dict]:
        return list(self._messages.get(session_id, []))

    def get_session(self, session_id: str) -> dict | None:
        return self._sessions.get(session_id)

    def list_sessions(self, limit: int = 20) -> list[dict]:
        return list(self._sessions.values())[:limit]

    def create_session(self, title: str | None = None, **_: Any) -> str:
        sid = "s-new"
        self._sessions[sid] = {
            "id": sid,
            "title": title or "Session New",
            "parent_session_id": None,
            "created_at": "2026-02-19T01:00:00+00:00",
            "updated_at": "2026-02-19T01:00:00+00:00",
            "status": "active",
        }
        self._messages[sid] = []
        return sid

    def set_session_title(self, session_id: str, title: str) -> None:
        self._sessions[session_id]["title"] = title

    def resolve_session_identifier(self, identifier: str) -> dict | None:
        identifier = identifier.strip()
        if identifier == "ambiguous":
            raise ValueError("ambiguous")
        if identifier in self._sessions:
            return self._sessions[identifier]
        for session in self._sessions.values():
            if session["title"].casefold() == identifier.casefold():
                return session
        return None

    def build_session_summary(self, session_id: str) -> dict:
        return {
            "session_id": session_id,
            "title": self._sessions[session_id]["title"],
            "created_at": "2026-02-19T00:00:00+00:00",
            "updated_at": "2026-02-19T00:10:00+00:00",
            "message_count": 2,
            "user_message_count": 1,
            "assistant_message_count": 1,
            "checkpoint_count": 1,
            "last_user_preview": "hello",
            "last_assistant_preview": "world",
        }

    def fork_session(self, source_session_id: str) -> str:
        sid = "s-fork"
        self._sessions[sid] = {
            "id": sid,
            "title": "Fork Session",
            "parent_session_id": source_session_id,
            "created_at": "2026-02-19T02:00:00+00:00",
            "updated_at": "2026-02-19T02:00:00+00:00",
            "status": "active",
        }
        self._messages[sid] = []
        return sid

    def append_message(self, session_id: str, role: str, content: str | list[dict]) -> tuple[str, int]:
        msgs = self._messages.setdefault(session_id, [])
        msgs.append({"role": role, "content": content})
        return f"m{len(msgs)}", len(msgs)

    def record_tool_call(self, *args: Any, **kwargs: Any) -> str:
        return "tc1"


class CheckpointManagerFake:
    """In-memory checkpoint manager for command-level tests."""

    enabled = True
    write_tools_only = True

    def __init__(self) -> None:
        self.created: list[str] = []
        self.rewinds: list[str] = []

    def create_checkpoint(self, session_id: str, user_message_id: str, scope: dict | None = None) -> str:
        cid = "cp1"
        self.created.append(cid)
        return cid

    def maybe_track_tool_input(self, checkpoint_id: str, tool_input: dict) -> list[str]:
        return []

    def list_checkpoints(self, session_id: str, limit: int = 20) -> list[dict]:
        return [
            {
                "id": "cp1",
                "created_at": "2026-02-19T00:05:00+00:00",
                "tools": ["write_file"],
                "user_preview": "update file",
            }
        ]

    def rewind_files(self, checkpoint_id: str) -> tuple[str, list[dict[str, str]]]:
        self.rewinds.append(checkpoint_id)
        return "s1", [{"path": "x.txt", "status": "restored", "detail": ""}]
