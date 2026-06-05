"""CommandHandler — the slash-command facade used by the agent loop.

Each command's implementation lives in its own per-command module; this
class only wires the shared ``CommandContext`` and forwards each public
``handle_*`` method to the matching module. The CommandRouter in
``agent.py`` binds these methods as callbacks.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from micro_x_agent_loop.api_payload_store import ApiPayloadStore
from micro_x_agent_loop.commands import (
    checkpoint_command,
    codegen_command,
    compact_command,
    console_command,
    cost_command,
    debug_command,
    help_command,
    memory_command,
    replay_command,
    routing_command,
    session_command,
    tool_command,
    tools_command,
    voice_command_handler,
)
from micro_x_agent_loop.commands.command_context import CommandContext
from micro_x_agent_loop.commands.prompt_commands import PromptCommandStore
from micro_x_agent_loop.memory.facade import ActiveMemoryFacade, NullMemoryFacade
from micro_x_agent_loop.metrics import SessionAccumulator
from micro_x_agent_loop.services.checkpoint_service import CheckpointService
from micro_x_agent_loop.services.session_controller import SessionController
from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.tool_result_formatter import ToolResultFormatter
from micro_x_agent_loop.voice_runtime import VoiceRuntime


class CommandHandler:
    """Implements all slash-command logic, decoupled from Agent state."""

    def __init__(
        self,
        *,
        line_prefix: str,
        session_accumulator: SessionAccumulator,
        memory: ActiveMemoryFacade | NullMemoryFacade,
        memory_enabled: bool,
        tool_map: dict[str, Tool],
        tool_result_formatter: ToolResultFormatter,
        api_payload_store: ApiPayloadStore,
        voice_runtime: VoiceRuntime | None,
        session_controller: SessionController,
        checkpoint_service: CheckpointService,
        user_memory_enabled: bool,
        user_memory_dir: str,
        prompt_command_store: PromptCommandStore,
        on_session_reset: Callable[[str, list[dict]], None],
        on_force_compact: Callable[[int | None], Awaitable[tuple[bool, str]]] | None = None,
        on_tools_deleted: Callable[[list[str]], None] | None = None,
        output: Callable[[str], None] = print,
        routing_feedback_store: object | None = None,
    ) -> None:
        self._print = output
        resolved_on_tools_deleted = on_tools_deleted or (lambda _tool_names: None)
        # CommandContext is the read-only bundle passed to every per-command
        # module. CommandHandler keeps it around and forwards each handle_*.
        self._ctx = CommandContext(
            line_prefix=line_prefix,
            print=self._print,
            session_accumulator=session_accumulator,
            memory=memory,
            memory_enabled=memory_enabled,
            tool_map=tool_map,
            tool_result_formatter=tool_result_formatter,
            api_payload_store=api_payload_store,
            voice_runtime=voice_runtime,
            session_controller=session_controller,
            checkpoint_service=checkpoint_service,
            user_memory_enabled=user_memory_enabled,
            user_memory_dir=user_memory_dir,
            prompt_command_store=prompt_command_store,
            on_session_reset=on_session_reset,
            on_force_compact=on_force_compact,
            on_tools_deleted=resolved_on_tools_deleted,
            routing_feedback_store=routing_feedback_store,
        )

    # -- Test-compat accessors --
    # The legacy CommandHandler exposed several state fields as private
    # attributes (`_memory`, `_tool_map`, `_tool_result_formatter`).
    # Several tests reach into those directly; preserve the surface
    # rather than rewriting every assertion.

    @property
    def _memory(self) -> ActiveMemoryFacade | NullMemoryFacade:
        return self._ctx.memory

    @property
    def _tool_map(self) -> dict[str, Tool]:
        return self._ctx.tool_map

    @property
    def _tool_result_formatter(self) -> ToolResultFormatter:
        return self._ctx.tool_result_formatter

    # -- /help and /command --

    async def on_help(self) -> None:
        await help_command.on_help(self._ctx)

    def on_unknown_command(self, trimmed: str) -> None:
        help_command.on_unknown_command(self._ctx, trimmed)

    async def handle_command(self, command: str) -> str | None:
        return await help_command.handle_command(self._ctx, command)

    # -- /console-log-level --

    async def handle_console_log_level(self, command: str) -> None:
        await console_command.handle_console_log_level(self._ctx, command)

    # -- /cost --

    async def handle_cost(self, command: str) -> None:
        await cost_command.handle_cost(self._ctx, command)

    # -- /replay --

    async def handle_replay(self, command: str) -> None:
        await replay_command.handle_replay(self._ctx, command)

    # -- /memory --

    async def handle_memory(self, command: str) -> None:
        await memory_command.handle_memory(self._ctx, command)

    # -- /codegen-task-list --

    async def handle_codegen_task_list(self, command: str) -> None:
        await codegen_command.handle_codegen_task_list(self._ctx, command)

    # -- /tools --

    async def handle_tools(self, command: str) -> None:
        await tools_command.handle_tools(self._ctx, command)

    # -- /tool --

    async def handle_tool(self, command: str) -> None:
        await tool_command.handle_tool(self._ctx, command)

    # -- /debug --

    async def handle_debug(self, command: str) -> None:
        await debug_command.handle_debug(self._ctx, command)

    # -- /session --

    async def handle_session(self, command: str) -> None:
        await session_command.handle_session(self._ctx, command)

    # -- /rewind --

    async def handle_rewind(self, command: str) -> None:
        await checkpoint_command.handle_rewind(self._ctx, command)

    # -- /checkpoint --

    async def handle_checkpoint(self, command: str) -> None:
        await checkpoint_command.handle_checkpoint(self._ctx, command)

    # -- /routing --

    async def handle_routing(self, command: str) -> None:
        await routing_command.handle_routing(self._ctx, command)

    # -- /voice --

    async def handle_voice(self, command: str) -> None:
        await voice_command_handler.handle_voice(self._ctx, command)

    # -- /compact --

    async def handle_compact(self, command: str) -> None:
        """Handle /compact [tail N] — force conversation compaction now."""
        await compact_command.handle_compact(self._ctx, command)
