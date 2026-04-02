"""TextualChannel — AgentChannel implementation for the Textual TUI."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from micro_x_agent_loop.tui.app import AgentTUI


class TextualChannel:
    """Bridges agent events to Textual widgets.

    The agent runs as an ``asyncio.create_task`` on the same event loop
    as the Textual app, so all calls are direct (no ``call_from_thread``).
    """

    # Signal to the agent that interactive terminal prompts (questionary,
    # input()) must not be used — the TUI owns the terminal.
    suppress_interactive_prompts: bool = True

    def __init__(self, app: AgentTUI) -> None:
        self._app = app

    # -- Agent → Client --

    def emit_text_delta(self, text: str) -> None:
        self._app.on_text_delta(text)

    def emit_tool_started(self, tool_use_id: str, tool_name: str) -> None:
        self._app.on_tool_started(tool_use_id, tool_name)

    def emit_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None:
        self._app.on_tool_completed(tool_use_id, tool_name, is_error)

    def emit_turn_complete(self, usage: dict[str, Any]) -> None:
        self._app.on_turn_complete(usage)

    def emit_error(self, message: str) -> None:
        self._app.on_agent_error(message)

    def emit_system_message(self, text: str) -> None:
        self._app.on_system_message(text)

    # -- Bidirectional --

    async def ask_user(self, question: str, options: list[dict[str, str]] | None = None) -> str:
        future: asyncio.Future[str] = asyncio.Future()
        self._app.on_ask_user(question, options, future)
        return await future

    # -- Streaming lifecycle (called by Agent._run_inner) --

    def begin_streaming(self) -> None:
        self._app.on_begin_streaming()

    def end_streaming(self) -> None:
        self._app.on_end_streaming()
