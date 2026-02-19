from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from micro_x_agent_loop.llm_client import Spinner
from micro_x_agent_loop.tool import Tool


class TurnEngine:
    def __init__(
        self,
        *,
        provider: Any,
        model: str,
        max_tokens: int,
        temperature: float,
        system_prompt: str,
        converted_tools: list[dict],
        tool_map: dict[str, Tool],
        line_prefix: str,
        max_tool_result_chars: int,
        max_tokens_retries: int,
        on_append_message: Callable[[str, str | list[dict]], str | None],
        on_user_message_appended: Callable[[str | None], None],
        on_maybe_compact: Callable[[], Awaitable[None]],
        on_ensure_checkpoint_for_turn: Callable[[list[dict]], None],
        on_maybe_track_mutation: Callable[[str, Tool, dict], None],
        on_record_tool_call: Callable[..., None],
        on_tool_started: Callable[[str, str], None],
        on_tool_completed: Callable[[str, str, bool], None],
    ) -> None:
        self._provider = provider
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._system_prompt = system_prompt
        self._converted_tools = converted_tools
        self._tool_map = tool_map
        self._line_prefix = line_prefix
        self._max_tool_result_chars = max_tool_result_chars
        self._max_tokens_retries = max_tokens_retries
        self._on_append_message = on_append_message
        self._on_user_message_appended = on_user_message_appended
        self._on_maybe_compact = on_maybe_compact
        self._on_ensure_checkpoint_for_turn = on_ensure_checkpoint_for_turn
        self._on_maybe_track_mutation = on_maybe_track_mutation
        self._on_record_tool_call = on_record_tool_call
        self._on_tool_started = on_tool_started
        self._on_tool_completed = on_tool_completed

    async def run(
        self,
        *,
        messages: list[dict],
        user_message: str,
    ) -> tuple[str | None, str | None]:
        last_assistant_message_id: str | None = None
        current_user_message_id = self._on_append_message("user", user_message)
        self._on_user_message_appended(current_user_message_id)
        await self._on_maybe_compact()

        max_tokens_attempts = 0

        while True:
            message, tool_use_blocks, stop_reason = await self._provider.stream_chat(
                self._model,
                self._max_tokens,
                self._temperature,
                self._system_prompt,
                messages,
                self._converted_tools,
                line_prefix=self._line_prefix,
            )

            last_assistant_message_id = self._on_append_message("assistant", message["content"])

            if stop_reason == "max_tokens" and not tool_use_blocks:
                max_tokens_attempts += 1
                if max_tokens_attempts >= self._max_tokens_retries:
                    print(
                        f"\n{self._line_prefix}[Stopped: response exceeded max_tokens "
                        f"({self._max_tokens}) {self._max_tokens_retries} times in a row. "
                        f"Try increasing MaxTokens in config.json or simplifying the request.]",
                    )
                    return current_user_message_id, last_assistant_message_id
                self._on_append_message(
                    "user",
                    (
                        "Your response was cut off because it exceeded the token limit. "
                        "Please continue, but be more concise. If you were writing a file, "
                        "break it into smaller sections or shorten the content."
                    ),
                )
                print()
                continue

            max_tokens_attempts = 0

            if not tool_use_blocks:
                return current_user_message_id, last_assistant_message_id

            tool_names = ", ".join(b["name"] for b in tool_use_blocks)
            spinner = Spinner(prefix=self._line_prefix, label=f" Running {tool_names}...")
            spinner.start()
            try:
                self._on_ensure_checkpoint_for_turn(tool_use_blocks)
                tool_results = await self.execute_tools(tool_use_blocks, last_assistant_message_id=last_assistant_message_id)
            finally:
                spinner.stop()
            self._on_append_message("user", tool_results)
            await self._on_maybe_compact()
            print()

    async def execute_tools(self, tool_use_blocks: list[dict], *, last_assistant_message_id: str | None) -> list[dict]:
        async def run_one(block: dict) -> dict:
            tool_name = block["name"]
            tool_use_id = block["id"]
            tool = self._tool_map.get(tool_name)
            tool_input = block["input"]

            self._on_tool_started(tool_use_id, tool_name)

            if tool is None:
                content = f'Error: unknown tool "{tool_name}"'
                self._on_record_tool_call(
                    tool_call_id=tool_use_id,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    result_text=content,
                    is_error=True,
                    message_id=last_assistant_message_id,
                )
                self._on_tool_completed(tool_use_id, tool_name, True)
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                    "is_error": True,
                }

            try:
                self._on_maybe_track_mutation(tool_name, tool, tool_input)
                result = await tool.execute(tool_input)
                result = self._truncate_tool_result(result, tool_name)
                self._on_record_tool_call(
                    tool_call_id=tool_use_id,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    result_text=result,
                    is_error=False,
                    message_id=last_assistant_message_id,
                )
                self._on_tool_completed(tool_use_id, tool_name, False)
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result,
                }
            except Exception as ex:
                content = f'Error executing tool "{tool_name}": {ex}'
                self._on_record_tool_call(
                    tool_call_id=tool_use_id,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    result_text=content,
                    is_error=True,
                    message_id=last_assistant_message_id,
                )
                self._on_tool_completed(tool_use_id, tool_name, True)
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                    "is_error": True,
                }

        return list(await asyncio.gather(*(run_one(b) for b in tool_use_blocks)))

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
