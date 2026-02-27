"""TurnEvents — callback protocol for TurnEngine lifecycle events."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.usage import UsageResult


@runtime_checkable
class TurnEvents(Protocol):
    def on_append_message(self, role: str, content: str | list[dict]) -> str | None: ...

    def on_user_message_appended(self, message_id: str | None) -> None: ...

    async def on_maybe_compact(self) -> None: ...

    def on_ensure_checkpoint_for_turn(self, tool_use_blocks: list[dict]) -> None: ...

    def on_maybe_track_mutation(self, tool_name: str, tool: Tool, tool_input: dict) -> None: ...

    def on_record_tool_call(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        tool_input: dict,
        result_text: str,
        is_error: bool,
        message_id: str | None,
    ) -> None: ...

    def on_tool_started(self, tool_use_id: str, tool_name: str) -> None: ...

    def on_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None: ...

    def on_api_call_completed(self, usage: UsageResult, call_type: str) -> None: ...

    def on_tool_executed(
        self, tool_name: str, result_chars: int, duration_ms: float, is_error: bool,
        *, was_summarized: bool = False,
    ) -> None: ...


class BaseTurnEvents:
    """Base class with no-op defaults for all ``TurnEvents`` methods."""

    def on_append_message(self, role: str, content: str | list[dict]) -> str | None:
        return None

    def on_user_message_appended(self, message_id: str | None) -> None:
        return

    async def on_maybe_compact(self) -> None:
        return

    def on_ensure_checkpoint_for_turn(self, tool_use_blocks: list[dict]) -> None:
        return

    def on_maybe_track_mutation(self, tool_name: str, tool: Tool, tool_input: dict) -> None:
        return

    def on_record_tool_call(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        tool_input: dict,
        result_text: str,
        is_error: bool,
        message_id: str | None,
    ) -> None:
        return

    def on_tool_started(self, tool_use_id: str, tool_name: str) -> None:
        return

    def on_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None:
        return

    def on_api_call_completed(self, usage: UsageResult, call_type: str) -> None:
        return

    def on_tool_executed(
        self, tool_name: str, result_chars: int, duration_ms: float, is_error: bool,
        *, was_summarized: bool = False,
    ) -> None:
        return

