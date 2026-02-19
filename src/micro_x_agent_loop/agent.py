import asyncio
from typing import Any

from loguru import logger

from micro_x_agent_loop.agent_config import AgentConfig
from micro_x_agent_loop.llm_client import Spinner, create_client, stream_chat, to_anthropic_tools
from micro_x_agent_loop.tool import Tool


class Agent:
    def __init__(self, config: AgentConfig):
        self._client = create_client(config.api_key)
        self._model = config.model
        self._max_tokens = config.max_tokens
        self._temperature = config.temperature
        self._system_prompt = config.system_prompt
        self._messages: list[dict] = []
        self._tool_map: dict[str, Tool] = {t.name: t for t in config.tools}
        self._anthropic_tools = to_anthropic_tools(config.tools)
        self._max_tool_result_chars = config.max_tool_result_chars
        self._max_conversation_messages = config.max_conversation_messages
        self._compaction_strategy = config.compaction_strategy
        self._memory_enabled = config.memory_enabled
        self._session_manager = config.session_manager
        self._checkpoint_manager = config.checkpoint_manager
        self._event_emitter = config.event_emitter
        self._active_session_id = config.session_id
        self._current_user_message_id: str | None = None
        self._current_checkpoint_id: str | None = None
        self._last_assistant_message_id: str | None = None

    _LINE_PREFIX = "assistant> "

    _MAX_TOKENS_RETRIES = 3
    _MUTATING_TOOL_NAMES = {"write_file", "append_file"}

    async def initialize_session(self) -> None:
        if not self._memory_enabled or self._session_manager is None or self._active_session_id is None:
            return
        self._messages = self._session_manager.load_messages(self._active_session_id)
        logger.info(
            f"Loaded {len(self._messages)} persisted messages for session {self._active_session_id}"
        )

    async def run(self, user_message: str) -> None:
        if await self._handle_local_command(user_message):
            return

        self._current_checkpoint_id = None
        self._last_assistant_message_id = None
        self._current_user_message_id = self._append_message("user", user_message)
        await self._maybe_compact()

        max_tokens_attempts = 0

        while True:
            message, tool_use_blocks, stop_reason = await stream_chat(
                self._client,
                self._model,
                self._max_tokens,
                self._temperature,
                self._system_prompt,
                self._messages,
                self._anthropic_tools,
                line_prefix=self._LINE_PREFIX,
            )

            self._last_assistant_message_id = self._append_message("assistant", message["content"])

            if stop_reason == "max_tokens" and not tool_use_blocks:
                max_tokens_attempts += 1
                if max_tokens_attempts >= self._MAX_TOKENS_RETRIES:
                    print(
                        f"\n{self._LINE_PREFIX}[Stopped: response exceeded max_tokens "
                        f"({self._max_tokens}) {self._MAX_TOKENS_RETRIES} times in a row. "
                        f"Try increasing MaxTokens in config.json or simplifying the request.]",
                    )
                    return
                self._append_message(
                    "user",
                    (
                        "Your response was cut off because it exceeded the token limit. "
                        "Please continue, but be more concise. If you were writing a file, "
                        "break it into smaller sections or shorten the content."
                    ),
                )
                print()  # newline before next spinner
                continue

            max_tokens_attempts = 0

            if not tool_use_blocks:
                return

            tool_names = ", ".join(b["name"] for b in tool_use_blocks)
            spinner = Spinner(prefix=self._LINE_PREFIX, label=f" Running {tool_names}...")
            spinner.start()
            try:
                self._ensure_checkpoint_for_turn(tool_use_blocks)
                tool_results = await self._execute_tools(tool_use_blocks)
            finally:
                spinner.stop()
            self._append_message("user", tool_results)
            await self._maybe_compact()

            print()  # newline before next spinner

    async def _maybe_compact(self) -> None:
        self._messages = await self._compaction_strategy.maybe_compact(self._messages)
        self._trim_conversation_history()

    async def _execute_tools(self, tool_use_blocks: list[dict]) -> list[dict]:
        async def run_one(block: dict) -> dict:
            tool_name = block["name"]
            tool_use_id = block["id"]
            tool = self._tool_map.get(tool_name)
            tool_input = block["input"]

            if self._event_emitter is not None and self._active_session_id is not None:
                self._event_emitter.emit(
                    self._active_session_id,
                    "tool.started",
                    {"tool_use_id": tool_use_id, "tool_name": tool_name},
                )

            if tool is None:
                content = f'Error: unknown tool "{tool_name}"'
                self._record_tool_call(
                    tool_call_id=tool_use_id,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    result_text=content,
                    is_error=True,
                )
                result = {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                    "is_error": True,
                }
                if self._event_emitter is not None and self._active_session_id is not None:
                    self._event_emitter.emit(
                        self._active_session_id,
                        "tool.completed",
                        {"tool_use_id": tool_use_id, "tool_name": tool_name, "is_error": True},
                    )
                return result

            try:
                self._maybe_track_mutation(tool_name, tool, tool_input)
                result = await tool.execute(tool_input)
                result = self._truncate_tool_result(result, tool_name)
                self._record_tool_call(
                    tool_call_id=tool_use_id,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    result_text=result,
                    is_error=False,
                )
                payload = {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result,
                }
                if self._event_emitter is not None and self._active_session_id is not None:
                    self._event_emitter.emit(
                        self._active_session_id,
                        "tool.completed",
                        {"tool_use_id": tool_use_id, "tool_name": tool_name, "is_error": False},
                    )
                return payload
            except Exception as ex:
                content = f'Error executing tool "{tool_name}": {ex}'
                self._record_tool_call(
                    tool_call_id=tool_use_id,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    result_text=content,
                    is_error=True,
                )
                payload = {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                    "is_error": True,
                }
                if self._event_emitter is not None and self._active_session_id is not None:
                    self._event_emitter.emit(
                        self._active_session_id,
                        "tool.completed",
                        {"tool_use_id": tool_use_id, "tool_name": tool_name, "is_error": True},
                    )
                return payload

        results = await asyncio.gather(*(run_one(b) for b in tool_use_blocks))
        return list(results)

    def _truncate_tool_result(self, result: str, tool_name: str) -> str:
        if self._max_tool_result_chars <= 0 or len(result) <= self._max_tool_result_chars:
            return result

        original_length = len(result)
        truncated = result[: self._max_tool_result_chars]
        message = (
            f"\n\n[OUTPUT TRUNCATED: Showing {self._max_tool_result_chars:,} "
            f"of {original_length:,} characters from {tool_name}]"
        )
        logger.warning(
            f"{tool_name} output truncated from {original_length:,} "
            f"to {self._max_tool_result_chars:,} chars"
        )
        return truncated + message

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
            scope={"tool_names": tool_names},
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
            # Snapshot failures must not block tool execution.
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

    def _record_tool_call(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        tool_input: dict,
        result_text: str,
        is_error: bool,
    ) -> None:
        if (
            not self._memory_enabled
            or self._session_manager is None
            or self._active_session_id is None
        ):
            return
        self._session_manager.record_tool_call(
            self._active_session_id,
            message_id=self._last_assistant_message_id,
            tool_name=tool_name,
            tool_input=tool_input,
            result_text=result_text,
            is_error=is_error,
            tool_call_id=tool_call_id,
        )

    async def _handle_local_command(self, user_message: str) -> bool:
        trimmed = user_message.strip()
        if not trimmed.startswith("/"):
            return False

        if trimmed == "/help":
            self._print_help()
            return True

        if trimmed.startswith("/rewind"):
            await self._handle_rewind_command(trimmed)
            return True

        if trimmed.startswith("/session"):
            await self._handle_session_command(trimmed)
            return True

        print(f"{self._LINE_PREFIX}Unknown local command: {trimmed}")
        return True

    def _print_help(self) -> None:
        print(f"{self._LINE_PREFIX}Available commands:")
        print(f"{self._LINE_PREFIX}- /help")
        if self._memory_enabled:
            print(f"{self._LINE_PREFIX}- /session")
            print(f"{self._LINE_PREFIX}- /session list [limit]")
            print(f"{self._LINE_PREFIX}- /session resume <id>")
            print(f"{self._LINE_PREFIX}- /session fork")
            print(f"{self._LINE_PREFIX}- /rewind <checkpoint_id>")
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
            print(f"{self._LINE_PREFIX}Current session: {self._active_session_id}")
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
                marker = "*" if s["id"] == self._active_session_id else " "
                parent = s["parent_session_id"] or "-"
                print(
                    f"{self._LINE_PREFIX}{marker} {s['id']} "
                    f"(status={s['status']}, updated={s['updated_at']}, parent={parent})"
                )
            return

        if len(parts) >= 3 and parts[1] == "resume":
            target = parts[2]
            session = self._session_manager.get_session(target)
            if session is None:
                print(f"{self._LINE_PREFIX}Session not found: {target}")
                return
            self._active_session_id = target
            self._messages = self._session_manager.load_messages(target)
            print(f"{self._LINE_PREFIX}Resumed session {target} ({len(self._messages)} messages)")
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
            f"{self._LINE_PREFIX}Usage: /session | /session list [limit] | "
            "/session resume <id> | /session fork"
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

        print(f"{self._LINE_PREFIX}Rewind {checkpoint_id} results:")
        for outcome in outcomes:
            detail = outcome["detail"]
            suffix = f" ({detail})" if detail else ""
            print(f"{self._LINE_PREFIX}- {outcome['path']}: {outcome['status']}{suffix}")
