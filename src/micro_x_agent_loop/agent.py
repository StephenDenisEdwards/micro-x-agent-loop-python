from __future__ import annotations

import asyncio

from loguru import logger

from micro_x_agent_loop.agent_config import AgentConfig
from micro_x_agent_loop.commands.router import CommandRouter
from micro_x_agent_loop.commands.voice_command import parse_voice_command, parse_voice_start_options
from micro_x_agent_loop.provider import create_provider
from micro_x_agent_loop.services.checkpoint_service import CheckpointService
from micro_x_agent_loop.services.session_controller import SessionController
from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.turn_engine import TurnEngine
from micro_x_agent_loop.voice_runtime import VoiceRuntime


class Agent:
    _LINE_PREFIX = "assistant> "
    _USER_PROMPT = "you> "

    _MAX_TOKENS_RETRIES = 3
    _MUTATING_TOOL_NAMES = {"write_file", "append_file"}

    def __init__(self, config: AgentConfig):
        self._provider = create_provider(config.provider, config.api_key)
        self._model = config.model
        self._max_tokens = config.max_tokens
        self._temperature = config.temperature
        self._system_prompt = config.system_prompt
        self._messages: list[dict] = []
        self._tool_map: dict[str, Tool] = {t.name: t for t in config.tools}
        self._converted_tools = self._provider.convert_tools(config.tools)
        self._max_tool_result_chars = config.max_tool_result_chars
        self._max_conversation_messages = config.max_conversation_messages
        self._compaction_strategy = config.compaction_strategy
        self._memory_enabled = config.memory_enabled
        self._session_manager = config.session_manager
        self._checkpoint_manager = config.checkpoint_manager
        self._event_emitter = config.event_emitter
        self._active_session_id = config.session_id
        self._current_user_message_id: str | None = None
        self._current_user_message_text: str | None = None
        self._current_checkpoint_id: str | None = None
        self._last_assistant_message_id: str | None = None
        self._run_lock = asyncio.Lock()

        self._voice_runtime = VoiceRuntime(
            line_prefix=self._LINE_PREFIX,
            tool_map=self._tool_map,
            on_utterance=self._process_voice_utterance,
        )

        self._session_controller = SessionController(line_prefix=self._LINE_PREFIX)
        self._checkpoint_service = CheckpointService(line_prefix=self._LINE_PREFIX)

        self._turn_engine = TurnEngine(
            provider=self._provider,
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            system_prompt=self._system_prompt,
            converted_tools=self._converted_tools,
            tool_map=self._tool_map,
            line_prefix=self._LINE_PREFIX,
            max_tool_result_chars=self._max_tool_result_chars,
            max_tokens_retries=self._MAX_TOKENS_RETRIES,
            on_append_message=self._append_message,
            on_user_message_appended=self._set_current_user_message_id,
            on_maybe_compact=self._maybe_compact,
            on_ensure_checkpoint_for_turn=self._ensure_checkpoint_for_turn,
            on_maybe_track_mutation=self._maybe_track_mutation,
            on_record_tool_call=self._record_tool_call,
            on_tool_started=self._emit_tool_started,
            on_tool_completed=self._emit_tool_completed,
        )

        self._command_router = CommandRouter(
            on_help=self._on_help,
            on_rewind=self._handle_rewind_command,
            on_checkpoint=self._handle_checkpoint_command,
            on_session=self._handle_session_command,
            on_voice=self._handle_voice_command,
            on_unknown=self._on_unknown_command,
        )

    async def initialize_session(self) -> None:
        if not self._memory_enabled or self._session_manager is None or self._active_session_id is None:
            return
        self._messages = self._session_manager.load_messages(self._active_session_id)
        logger.info(
            f"Loaded {len(self._messages)} persisted messages for session {self._active_session_id}"
        )

    async def run(self, user_message: str) -> None:
        async with self._run_lock:
            await self._run_inner(user_message)

    async def _run_inner(self, user_message: str) -> None:
        if await self._handle_local_command(user_message):
            return

        self._current_checkpoint_id = None
        self._last_assistant_message_id = None
        self._current_user_message_text = user_message
        current_user_message_id, last_assistant_message_id = await self._turn_engine.run(
            messages=self._messages,
            user_message=user_message,
        )
        self._current_user_message_id = current_user_message_id
        self._last_assistant_message_id = last_assistant_message_id

    async def _maybe_compact(self) -> None:
        self._messages = await self._compaction_strategy.maybe_compact(self._messages)
        self._trim_conversation_history()

    def _trim_conversation_history(self) -> None:
        if self._max_conversation_messages <= 0:
            return
        if len(self._messages) <= self._max_conversation_messages:
            return

        remove_count = len(self._messages) - self._max_conversation_messages
        if remove_count > 0:
            logger.info(
                f"Conversation history trimmed - removed {remove_count} oldest message(s) "
                f"to stay within the {self._max_conversation_messages} message limit"
            )
            del self._messages[:remove_count]

    def _append_message(self, role: str, content: str | list[dict]) -> str | None:
        self._messages.append({"role": role, "content": content})
        if (
            self._memory_enabled
            and self._session_manager is not None
            and self._active_session_id is not None
        ):
            message_id, _ = self._session_manager.append_message(self._active_session_id, role, content)
            return message_id
        return None

    def _ensure_checkpoint_for_turn(self, tool_use_blocks: list[dict]) -> None:
        if (
            not self._memory_enabled
            or self._checkpoint_manager is None
            or not self._checkpoint_manager.enabled
            or self._active_session_id is None
            or self._current_user_message_id is None
            or self._current_checkpoint_id is not None
        ):
            return
        tool_names = [b["name"] for b in tool_use_blocks]
        self._current_checkpoint_id = self._checkpoint_manager.create_checkpoint(
            self._active_session_id,
            self._current_user_message_id,
            scope={
                "tool_names": tool_names,
                "user_preview": (self._current_user_message_text or "")[:120],
            },
        )

    def _maybe_track_mutation(self, tool_name: str, tool: Tool, tool_input: dict) -> None:
        if (
            not self._memory_enabled
            or self._checkpoint_manager is None
            or not self._checkpoint_manager.enabled
            or self._current_checkpoint_id is None
        ):
            return
        if self._checkpoint_manager.write_tools_only and tool_name not in self._MUTATING_TOOL_NAMES:
            return
        is_mutating = bool(getattr(tool, "is_mutating", False))
        if not is_mutating and tool_name not in self._MUTATING_TOOL_NAMES:
            return
        try:
            self._checkpoint_manager.maybe_track_tool_input(self._current_checkpoint_id, tool_input)
        except Exception as ex:
            logger.warning(
                f"Checkpoint tracking failed for tool '{tool_name}' "
                f"(checkpoint={self._current_checkpoint_id}): {ex}"
            )
            if self._event_emitter is not None and self._active_session_id is not None:
                self._event_emitter.emit(
                    self._active_session_id,
                    "checkpoint.file_untracked",
                    {
                        "checkpoint_id": self._current_checkpoint_id,
                        "tool_name": tool_name,
                        "error": str(ex),
                    },
                )

    def _emit_tool_started(self, tool_use_id: str, tool_name: str) -> None:
        if self._event_emitter is not None and self._active_session_id is not None:
            self._event_emitter.emit(
                self._active_session_id,
                "tool.started",
                {"tool_use_id": tool_use_id, "tool_name": tool_name},
            )

    def _set_current_user_message_id(self, message_id: str | None) -> None:
        self._current_user_message_id = message_id

    def _emit_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None:
        if self._event_emitter is not None and self._active_session_id is not None:
            self._event_emitter.emit(
                self._active_session_id,
                "tool.completed",
                {"tool_use_id": tool_use_id, "tool_name": tool_name, "is_error": is_error},
            )

    def _record_tool_call(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        tool_input: dict,
        result_text: str,
        is_error: bool,
        message_id: str | None,
    ) -> None:
        if (
            not self._memory_enabled
            or self._session_manager is None
            or self._active_session_id is None
        ):
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

    async def _handle_local_command(self, user_message: str) -> bool:
        return await self._command_router.try_handle(user_message)

    async def _on_help(self) -> None:
        self._print_help()

    def _on_unknown_command(self, trimmed: str) -> None:
        print(f"{self._LINE_PREFIX}Unknown local command: {trimmed}")

    def _print_help(self) -> None:
        print(f"{self._LINE_PREFIX}Available commands:")
        print(f"{self._LINE_PREFIX}- /help")
        print(
            f"{self._LINE_PREFIX}- /voice start [microphone|loopback] "
            "[--mic-device-id <id>] [--mic-device-name <name>] "
            "[--chunk-seconds <n>] [--endpointing-ms <n>] [--utterance-end-ms <n>]"
        )
        print(f"{self._LINE_PREFIX}- /voice status")
        print(f"{self._LINE_PREFIX}- /voice devices")
        print(f"{self._LINE_PREFIX}- /voice events [limit]")
        print(f"{self._LINE_PREFIX}- /voice stop")
        if self._memory_enabled:
            print(f"{self._LINE_PREFIX}- /session")
            print(f"{self._LINE_PREFIX}- /session new [title]")
            print(f"{self._LINE_PREFIX}- /session list [limit]")
            print(f"{self._LINE_PREFIX}- /session name <title>")
            print(f"{self._LINE_PREFIX}- /session resume <id-or-name>")
            print(f"{self._LINE_PREFIX}- /session fork")
            print(f"{self._LINE_PREFIX}- /rewind <checkpoint_id>")
            print(f"{self._LINE_PREFIX}- /checkpoint list [limit]")
            print(f"{self._LINE_PREFIX}- /checkpoint rewind <checkpoint_id>")
        else:
            print(
                f"{self._LINE_PREFIX}Memory commands are available when MemoryEnabled=true "
                "(see operations/config.md)."
            )

    async def _handle_session_command(self, command: str) -> None:
        if not self._memory_enabled or self._session_manager is None:
            print(f"{self._LINE_PREFIX}Session commands require MemoryEnabled=true")
            return

        parts = command.split()
        if len(parts) == 1:
            if self._active_session_id is None:
                print(f"{self._LINE_PREFIX}Current session: none")
                return
            session = self._session_manager.get_session(self._active_session_id)
            title = session.get("title", self._active_session_id) if session else self._active_session_id
            print(
                f"{self._LINE_PREFIX}Current session: {title} "
                f"[{self._session_controller.short_id(self._active_session_id)}] (id={self._active_session_id})"
            )
            return

        if len(parts) >= 2 and parts[1] == "list":
            limit = 20
            if len(parts) >= 3:
                try:
                    limit = int(parts[2])
                except ValueError:
                    print(f"{self._LINE_PREFIX}Usage: /session list [limit]")
                    return
            sessions = self._session_manager.list_sessions(limit=limit)
            if not sessions:
                print(f"{self._LINE_PREFIX}No sessions found.")
                return
            print(f"{self._LINE_PREFIX}Recent sessions:")
            for s in sessions:
                print(self._session_controller.format_session_list_entry(s, active_session_id=self._active_session_id))
            return

        if len(parts) >= 2 and parts[1] == "new":
            title = command.partition("new")[2].strip()
            new_id = self._session_manager.create_session(title=title if title else None)
            self._active_session_id = new_id
            self._messages = self._session_manager.load_messages(new_id)
            session = self._session_manager.get_session(new_id) or {"title": new_id}
            print(
                f"{self._LINE_PREFIX}Started new session: {session.get('title', new_id)} "
                f"[{self._session_controller.short_id(new_id)}] (id={new_id})"
            )
            return

        if len(parts) >= 3 and parts[1] == "name":
            if self._active_session_id is None:
                print(f"{self._LINE_PREFIX}No active session to name")
                return
            title = command.partition("name")[2].strip()
            if not title:
                print(f"{self._LINE_PREFIX}Usage: /session name <title>")
                return
            self._session_manager.set_session_title(self._active_session_id, title)
            print(f"{self._LINE_PREFIX}Session named: {title}")
            return

        if len(parts) >= 3 and parts[1] == "resume":
            target = command.partition("resume")[2].strip()
            if not target:
                print(f"{self._LINE_PREFIX}Usage: /session resume <id-or-name>")
                return
            try:
                session = self._session_manager.resolve_session_identifier(target)
            except ValueError as ex:
                print(f"{self._LINE_PREFIX}{ex}")
                return
            if session is None:
                print(f"{self._LINE_PREFIX}Session not found: {target}")
                return
            resolved_id = session["id"]
            self._active_session_id = resolved_id
            self._messages = self._session_manager.load_messages(resolved_id)
            summary = self._session_manager.build_session_summary(resolved_id)
            print(
                f"{self._LINE_PREFIX}Resumed session {summary['title']} "
                f"[{self._session_controller.short_id(resolved_id)}] (id={resolved_id}, {len(self._messages)} messages)"
            )
            for line in self._session_controller.format_resumed_summary_lines(summary):
                print(line)
            return

        if len(parts) == 2 and parts[1] == "fork":
            if self._active_session_id is None:
                print(f"{self._LINE_PREFIX}No active session to fork")
                return
            source_id = self._active_session_id
            fork_id = self._session_manager.fork_session(source_id)
            self._active_session_id = fork_id
            self._messages = self._session_manager.load_messages(fork_id)
            print(f"{self._LINE_PREFIX}Forked session {source_id} -> {fork_id}")
            return

        print(
            f"{self._LINE_PREFIX}Usage: /session | /session new [title] | /session list [limit] | "
            "/session name <title> | /session resume <id-or-name> | /session fork"
        )

    async def _handle_rewind_command(self, command: str) -> None:
        if not self._memory_enabled or self._checkpoint_manager is None:
            print(f"{self._LINE_PREFIX}Rewind requires MemoryEnabled=true")
            return
        parts = command.split()
        if len(parts) != 2:
            print(f"{self._LINE_PREFIX}Usage: /rewind <checkpoint_id>")
            return

        checkpoint_id = parts[1]
        try:
            _, outcomes = self._checkpoint_manager.rewind_files(checkpoint_id)
        except Exception as ex:
            print(f"{self._LINE_PREFIX}Rewind failed: {ex}")
            return

        for line in self._checkpoint_service.format_rewind_outcome_lines(checkpoint_id, outcomes):
            print(line)

    async def _handle_checkpoint_command(self, command: str) -> None:
        if (
            not self._memory_enabled
            or self._checkpoint_manager is None
            or self._active_session_id is None
        ):
            print(f"{self._LINE_PREFIX}Checkpoint commands require MemoryEnabled=true")
            return

        parts = command.split()
        if len(parts) == 1 or (len(parts) >= 2 and parts[1] == "list"):
            limit = 20
            if len(parts) >= 3:
                try:
                    limit = int(parts[2])
                except ValueError:
                    print(f"{self._LINE_PREFIX}Usage: /checkpoint list [limit]")
                    return
            checkpoints = self._checkpoint_manager.list_checkpoints(self._active_session_id, limit=limit)
            if not checkpoints:
                print(f"{self._LINE_PREFIX}No checkpoints found for current session.")
                return
            print(f"{self._LINE_PREFIX}Recent checkpoints:")
            for cp in checkpoints:
                print(self._checkpoint_service.format_checkpoint_list_entry(cp))
            return

        if len(parts) == 3 and parts[1] == "rewind":
            await self._handle_rewind_command(f"/rewind {parts[2]}")
            return

        print(
            f"{self._LINE_PREFIX}Usage: /checkpoint list [limit] | /checkpoint rewind <checkpoint_id>"
        )

    async def _handle_voice_command(self, command: str) -> None:
        try:
            parts = parse_voice_command(command)
        except ValueError:
            print(f"{self._LINE_PREFIX}Invalid command syntax")
            return
        if len(parts) == 1:
            print(
                f"{self._LINE_PREFIX}Usage: /voice start [microphone|loopback] "
                "[--mic-device-id <id>] [--mic-device-name <name>] "
                "[--chunk-seconds <n>] [--endpointing-ms <n>] [--utterance-end-ms <n>] | "
                "/voice status | /voice devices | /voice events [limit] | /voice stop"
            )
            return

        action = parts[1].lower()
        if action == "start":
            opts, error = parse_voice_start_options(parts, line_prefix=self._LINE_PREFIX)
            if error:
                print(error)
                return
            assert opts is not None
            print(
                await self._voice_runtime.start(
                    opts.source,
                    opts.mic_device_id,
                    opts.mic_device_name,
                    opts.chunk_seconds,
                    opts.endpointing_ms,
                    opts.utterance_end_ms,
                )
            )
            return

        if action == "status":
            print(await self._voice_runtime.status())
            return

        if action == "devices":
            print(await self._voice_runtime.devices())
            return

        if action == "events":
            limit = 50
            if len(parts) >= 3:
                try:
                    limit = int(parts[2])
                except ValueError:
                    print(f"{self._LINE_PREFIX}Usage: /voice events [limit]")
                    return
            print(await self._voice_runtime.events(limit))
            return

        if action == "stop":
            print(await self._voice_runtime.stop())
            return

        print(
            f"{self._LINE_PREFIX}Usage: /voice start [microphone|loopback] "
            "[--mic-device-id <id>] [--mic-device-name <name>] "
            "[--chunk-seconds <n>] [--endpointing-ms <n>] [--utterance-end-ms <n>] | "
            "/voice status | /voice devices | /voice events [limit] | /voice stop"
        )

    async def _process_voice_utterance(self, text: str) -> None:
        await self.run(text)
        print(f"\n{self._USER_PROMPT}", end="", flush=True)

    async def shutdown(self) -> None:
        await self._voice_runtime.shutdown()

    @property
    def active_session_id(self) -> str | None:
        return self._active_session_id

    # Backward-compatible wrappers for existing tests.
    async def _execute_tools(self, tool_use_blocks: list[dict]) -> list[dict]:
        return await self._turn_engine.execute_tools(
            tool_use_blocks,
            last_assistant_message_id=self._last_assistant_message_id,
        )

    def _short_id(self, value: str, length: int = 8) -> str:
        _ = length
        return self._session_controller.short_id(value)

    def _format_session_list_entry(self, session: dict) -> str:
        return self._session_controller.format_session_list_entry(session, active_session_id=self._active_session_id)

    def _format_checkpoint_list_entry(self, checkpoint: dict) -> str:
        return self._checkpoint_service.format_checkpoint_list_entry(checkpoint)

    def _print_resumed_session_summary(self, summary: dict) -> None:
        for line in self._session_controller.format_resumed_summary_lines(summary):
            print(line)
