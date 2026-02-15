import asyncio
import sys
from typing import Any

from micro_x_agent_loop.agent_config import AgentConfig
from micro_x_agent_loop.llm_client import create_client, stream_chat, to_anthropic_tools
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

    async def run(self, user_message: str) -> None:
        self._messages.append({"role": "user", "content": user_message})
        self._trim_conversation_history()

        while True:
            message, tool_use_blocks = await stream_chat(
                self._client,
                self._model,
                self._max_tokens,
                self._temperature,
                self._system_prompt,
                self._messages,
                self._anthropic_tools,
            )

            self._messages.append(message)

            if not tool_use_blocks:
                return

            tool_results = await self._execute_tools(tool_use_blocks)
            self._messages.append({"role": "user", "content": tool_results})
            self._trim_conversation_history()

            print("\nassistant> ", end="", flush=True)

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
        print(
            f"  Warning: {tool_name} output truncated from {original_length:,} "
            f"to {self._max_tool_result_chars:,} chars",
            file=sys.stderr,
        )
        return truncated + message

    def _trim_conversation_history(self) -> None:
        if self._max_conversation_messages <= 0:
            return
        if len(self._messages) <= self._max_conversation_messages:
            return

        remove_count = len(self._messages) - self._max_conversation_messages
        if remove_count > 0:
            print(
                f"  Note: Conversation history trimmed — removed {remove_count} oldest message(s) "
                f"to stay within the {self._max_conversation_messages} message limit",
                file=sys.stderr,
            )
            del self._messages[:remove_count]
