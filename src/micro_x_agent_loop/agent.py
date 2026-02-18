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

    _LINE_PREFIX = "assistant> "

    _MAX_TOKENS_RETRIES = 3

    async def run(self, user_message: str) -> None:
        self._messages.append({"role": "user", "content": user_message})
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

            self._messages.append(message)

            if stop_reason == "max_tokens" and not tool_use_blocks:
                max_tokens_attempts += 1
                if max_tokens_attempts >= self._MAX_TOKENS_RETRIES:
                    print(
                        f"\n{self._LINE_PREFIX}[Stopped: response exceeded max_tokens "
                        f"({self._max_tokens}) {self._MAX_TOKENS_RETRIES} times in a row. "
                        f"Try increasing MaxTokens in config.json or simplifying the request.]",
                    )
                    return
                self._messages.append({
                    "role": "user",
                    "content": (
                        "Your response was cut off because it exceeded the token limit. "
                        "Please continue, but be more concise. If you were writing a file, "
                        "break it into smaller sections or shorten the content."
                    ),
                })
                print()  # newline before next spinner
                continue

            max_tokens_attempts = 0

            if not tool_use_blocks:
                return

            tool_names = ", ".join(b["name"] for b in tool_use_blocks)
            spinner = Spinner(prefix=self._LINE_PREFIX, label=f" Running {tool_names}...")
            spinner.start()
            try:
                tool_results = await self._execute_tools(tool_use_blocks)
            finally:
                spinner.stop()
            self._messages.append({"role": "user", "content": tool_results})
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

            if tool is None:
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": f'Error: unknown tool "{tool_name}"',
                    "is_error": True,
                }

            try:
                result = await tool.execute(block["input"])
                result = self._truncate_tool_result(result, tool_name)
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result,
                }
            except Exception as ex:
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": f'Error executing tool "{tool_name}": {ex}',
                    "is_error": True,
                }

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
                f"Conversation history trimmed — removed {remove_count} oldest message(s) "
                f"to stay within the {self._max_conversation_messages} message limit"
            )
            del self._messages[:remove_count]
