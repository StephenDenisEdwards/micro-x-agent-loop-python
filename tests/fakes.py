"""Shared test fakes used across the test suite."""

from __future__ import annotations

from typing import Any

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

    async def execute(self, tool_input: dict[str, Any]) -> str:
        self.execute_calls += 1
        if self._execute_side_effect is not None:
            raise self._execute_side_effect
        return self._execute_result


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
