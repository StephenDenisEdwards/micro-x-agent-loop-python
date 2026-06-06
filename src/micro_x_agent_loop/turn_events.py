"""TurnEvents — callback protocols for TurnEngine / ToolDispatcher events.

Split into two narrow protocols plus a unified one for back-compat:

- ``TurnObserver``      — read-only hooks (logs, metrics, traces).
- ``TurnStateRecorder`` — mutating hooks that write to the agent's message
                          history, memory store, and checkpoint state.
- ``TurnEvents``        — the union of both. ``TurnEngine`` and
                          ``ToolDispatcher`` accept this so a single
                          implementation can keep wiring everything; new
                          collaborators that only need to *observe* (or only
                          need to *record state*) should accept the narrower
                          subset.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.usage import UsageResult


@runtime_checkable
class TurnObserver(Protocol):
    """Read-only callbacks: logs, metrics, traces. No state mutation.

    Implementors must not change the conversation history, memory store, or
    checkpoint state from these methods — they exist so consumers can attach
    telemetry without affecting the loop.
    """

    def on_llm_call(
        self,
        *,
        turn_iteration: int,
        call_type: str,
        effective_provider: str,
        effective_model: str,
        temperature: float,
        max_tokens: int,
        message_count: int,
        tool_names: list[str],
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        routing_rule: str = "",
        routing_reason: str = "",
    ) -> None: ...

    def on_api_call_completed(self, usage: UsageResult, call_type: str) -> None: ...

    def on_api_call_failed(
        self, *, model: str, provider: str, call_type: str, error: BaseException
    ) -> None: ...

    def on_turn_cap_reached(self, iterations: int) -> None: ...

    def on_tool_executed(
        self,
        tool_name: str,
        result_chars: int,
        duration_ms: float,
        is_error: bool,
        *,
        was_summarized: bool = False,
    ) -> None: ...

    def on_subagent_completed(
        self,
        *,
        agent_type: str,
        task: str,
        result_summary: str,
        turns: int,
        timed_out: bool,
        cost_usd: float,
        api_calls: int,
    ) -> None: ...


@runtime_checkable
class TurnStateRecorder(Protocol):
    """Mutating callbacks: append messages, persist tool calls, manage
    checkpoints / compaction. These hooks change the agent's state."""

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
        was_truncated: bool = False,
        original_chars: int | None = None,
    ) -> None: ...

    def on_tool_started(self, tool_use_id: str, tool_name: str) -> None: ...

    def on_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None: ...


@runtime_checkable
class TurnEvents(TurnObserver, TurnStateRecorder, Protocol):
    """Union of ``TurnObserver`` and ``TurnStateRecorder``.

    The single, wire-it-up-and-forget protocol that ``TurnEngine`` and
    ``ToolDispatcher`` accept. New collaborators that only need a subset
    should declare ``TurnObserver`` or ``TurnStateRecorder`` instead, so the
    intent is documented at the call site.
    """


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
        was_truncated: bool = False,
        original_chars: int | None = None,
    ) -> None:
        return

    def on_llm_call(
        self,
        *,
        turn_iteration: int,
        call_type: str,
        effective_provider: str,
        effective_model: str,
        temperature: float,
        max_tokens: int,
        message_count: int,
        tool_names: list[str],
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        routing_rule: str = "",
        routing_reason: str = "",
    ) -> None:
        return

    def on_tool_started(self, tool_use_id: str, tool_name: str) -> None:
        return

    def on_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None:
        return

    def on_api_call_completed(self, usage: UsageResult, call_type: str) -> None:
        return

    def on_api_call_failed(
        self, *, model: str, provider: str, call_type: str, error: BaseException
    ) -> None:
        return

    def on_turn_cap_reached(self, iterations: int) -> None:
        return

    def on_tool_executed(
        self,
        tool_name: str,
        result_chars: int,
        duration_ms: float,
        is_error: bool,
        *,
        was_summarized: bool = False,
    ) -> None:
        return

    def on_subagent_completed(
        self,
        *,
        agent_type: str,
        task: str,
        result_summary: str,
        turns: int,
        timed_out: bool,
        cost_usd: float,
        api_calls: int,
    ) -> None:
        return
