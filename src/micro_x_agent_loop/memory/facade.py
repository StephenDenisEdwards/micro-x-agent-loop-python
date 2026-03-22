"""MemoryFacade — single entry point for all memory-related operations.

Provides ``ActiveMemoryFacade`` (real implementation) and ``NullMemoryFacade``
(no-op) so callers never need null-check guards.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from loguru import logger

from micro_x_agent_loop.tool import Tool

_MUTATING_TOOL_NAMES = {"write_file", "append_file", "filesystem__write_file", "filesystem__append_file"}


@runtime_checkable
class MemoryFacade(Protocol):
    @property
    def store(self) -> Any: ...

    @property
    def session_manager(self) -> Any: ...

    @property
    def checkpoint_manager(self) -> Any: ...

    @property
    def active_session_id(self) -> str | None: ...

    @active_session_id.setter
    def active_session_id(self, value: str | None) -> None: ...

    def append_message(self, role: str, content: str | list[dict]) -> str | None: ...

    def ensure_checkpoint_for_turn(
        self,
        tool_use_blocks: list[dict],
        *,
        user_message_id: str | None,
        user_message_text: str | None,
        current_checkpoint_id: str | None,
    ) -> str | None: ...

    def maybe_track_mutation(
        self, tool_name: str, tool: Tool, tool_input: dict, checkpoint_id: str | None
    ) -> None: ...

    def record_tool_call(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        tool_input: dict,
        result_text: str,
        is_error: bool,
        message_id: str | None,
    ) -> None: ...

    def emit_tool_started(self, tool_use_id: str, tool_name: str) -> None: ...

    def emit_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None: ...

    def emit_event(self, event_type: str, payload: dict) -> None: ...

    def load_messages(self, session_id: str) -> list[dict]: ...


class NullMemoryFacade:
    """No-op implementation for when memory is disabled."""

    @property
    def store(self) -> None:
        return None

    @property
    def session_manager(self) -> None:
        return None

    @property
    def checkpoint_manager(self) -> None:
        return None

    def __init__(self) -> None:
        self._active_session_id: str | None = None

    @property
    def active_session_id(self) -> str | None:
        return self._active_session_id

    @active_session_id.setter
    def active_session_id(self, value: str | None) -> None:
        self._active_session_id = value

    def append_message(self, role: str, content: str | list[dict]) -> str | None:
        return None

    def ensure_checkpoint_for_turn(
        self,
        tool_use_blocks: list[dict],
        *,
        user_message_id: str | None,
        user_message_text: str | None,
        current_checkpoint_id: str | None,
    ) -> str | None:
        return None

    def maybe_track_mutation(
        self, tool_name: str, tool: Tool, tool_input: dict, checkpoint_id: str | None
    ) -> None:
        return

    def record_tool_call(
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

    def emit_tool_started(self, tool_use_id: str, tool_name: str) -> None:
        return

    def emit_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None:
        return

    def emit_event(self, event_type: str, payload: dict) -> None:
        return

    def load_messages(self, session_id: str) -> list[dict]:
        return []


class ActiveMemoryFacade:
    """Real implementation wrapping SessionManager + CheckpointManager + EventEmitter."""

    def __init__(
        self,
        session_manager: Any,
        checkpoint_manager: Any | None,
        event_emitter: Any | None,
        active_session_id: str | None,
        store: Any | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._checkpoint_manager = checkpoint_manager
        self._event_emitter = event_emitter
        self._active_session_id = active_session_id
        self._store = store

    @property
    def store(self) -> Any:
        return self._store

    @property
    def session_manager(self) -> Any:
        return self._session_manager

    @property
    def checkpoint_manager(self) -> Any:
        return self._checkpoint_manager

    @property
    def active_session_id(self) -> str | None:
        return self._active_session_id

    @active_session_id.setter
    def active_session_id(self, value: str | None) -> None:
        self._active_session_id = value

    def append_message(self, role: str, content: str | list[dict]) -> str | None:
        if self._session_manager is None or self._active_session_id is None:
            return None
        message_id, _ = self._session_manager.append_message(self._active_session_id, role, content)
        return str(message_id) if message_id is not None else None

    def ensure_checkpoint_for_turn(
        self,
        tool_use_blocks: list[dict],
        *,
        user_message_id: str | None,
        user_message_text: str | None,
        current_checkpoint_id: str | None,
    ) -> str | None:
        if (
            self._checkpoint_manager is None
            or not self._checkpoint_manager.enabled
            or self._active_session_id is None
            or user_message_id is None
            or current_checkpoint_id is not None
        ):
            return None
        tool_names = [b["name"] for b in tool_use_blocks]
        result: str | None = self._checkpoint_manager.create_checkpoint(
            self._active_session_id,
            user_message_id,
            scope={
                "tool_names": tool_names,
                "user_preview": (user_message_text or "")[:120],
            },
        )
        return result

    def maybe_track_mutation(
        self, tool_name: str, tool: Tool, tool_input: dict, checkpoint_id: str | None
    ) -> None:
        if (
            self._checkpoint_manager is None
            or not self._checkpoint_manager.enabled
            or checkpoint_id is None
        ):
            return
        if self._checkpoint_manager.write_tools_only and tool_name not in _MUTATING_TOOL_NAMES:
            return
        is_mutating = bool(getattr(tool, "is_mutating", False))
        if not is_mutating and tool_name not in _MUTATING_TOOL_NAMES:
            return
        try:
            predict = getattr(tool, "predict_touched_paths", None)
            if callable(predict):
                paths = predict(tool_input)
                if paths:
                    self._checkpoint_manager.track_paths(checkpoint_id, paths)
                else:
                    self._checkpoint_manager.maybe_track_tool_input(checkpoint_id, tool_input)
            else:
                self._checkpoint_manager.maybe_track_tool_input(checkpoint_id, tool_input)
        except Exception as ex:
            logger.warning(
                f"Checkpoint tracking failed for tool '{tool_name}' "
                f"(checkpoint={checkpoint_id}): {ex}"
            )
            if self._event_emitter is not None and self._active_session_id is not None:
                self._event_emitter.emit(
                    self._active_session_id,
                    "checkpoint.file_untracked",
                    {
                        "checkpoint_id": checkpoint_id,
                        "tool_name": tool_name,
                        "error": str(ex),
                    },
                )

    def record_tool_call(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        tool_input: dict,
        result_text: str,
        is_error: bool,
        message_id: str | None,
    ) -> None:
        if self._session_manager is None or self._active_session_id is None:
            return
        self._session_manager.record_tool_call(
            self._active_session_id,
            message_id=message_id,
            tool_name=tool_name,
            tool_input=tool_input,
            result_text=result_text,
            is_error=is_error,
            tool_call_id=tool_call_id,
        )

    def emit_tool_started(self, tool_use_id: str, tool_name: str) -> None:
        if self._event_emitter is not None and self._active_session_id is not None:
            self._event_emitter.emit(
                self._active_session_id,
                "tool.started",
                {"tool_use_id": tool_use_id, "tool_name": tool_name},
            )

    def emit_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None:
        if self._event_emitter is not None and self._active_session_id is not None:
            self._event_emitter.emit(
                self._active_session_id,
                "tool.completed",
                {"tool_use_id": tool_use_id, "tool_name": tool_name, "is_error": is_error},
            )

    def emit_event(self, event_type: str, payload: dict) -> None:
        if self._event_emitter is not None and self._active_session_id is not None:
            self._event_emitter.emit(self._active_session_id, event_type, payload)

    def load_messages(self, session_id: str) -> list[dict]:
        result: list[dict] = self._session_manager.load_messages(session_id)
        return result
