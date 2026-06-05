"""Shared context for slash-command handlers.

Each per-command module takes a ``CommandContext`` so it can access the
collaborators (memory, accumulator, tool map, voice runtime, etc.) without
holding a reference to the full ``CommandHandler``. ``CommandHandler``
builds one ``CommandContext`` in its constructor and reuses it for every
delegated call.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from micro_x_agent_loop.api_payload_store import ApiPayloadStore
from micro_x_agent_loop.commands.prompt_commands import PromptCommandStore
from micro_x_agent_loop.memory.facade import ActiveMemoryFacade, NullMemoryFacade
from micro_x_agent_loop.metrics import SessionAccumulator
from micro_x_agent_loop.services.checkpoint_service import CheckpointService
from micro_x_agent_loop.services.session_controller import SessionController
from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.tool_result_formatter import ToolResultFormatter
from micro_x_agent_loop.voice_runtime import VoiceRuntime


@dataclass(frozen=True)
class CommandContext:
    """Read-only bundle of state shared by every slash-command handler."""

    line_prefix: str
    print: Callable[[str], None]
    session_accumulator: SessionAccumulator
    memory: ActiveMemoryFacade | NullMemoryFacade
    memory_enabled: bool
    tool_map: dict[str, Tool]
    tool_result_formatter: ToolResultFormatter
    api_payload_store: ApiPayloadStore
    voice_runtime: VoiceRuntime | None
    session_controller: SessionController
    checkpoint_service: CheckpointService
    user_memory_enabled: bool
    user_memory_dir: str
    prompt_command_store: PromptCommandStore
    on_session_reset: Callable[[str, list[dict]], None]
    on_force_compact: Callable[[int | None], Awaitable[tuple[bool, str]]] | None
    on_tools_deleted: Callable[[list[str]], None]
    routing_feedback_store: object | None
