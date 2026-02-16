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
        self._input_token_budget = config.input_token_budget
        self._tool_result_retention_chars = config.tool_result_retention_chars

    _LINE_PREFIX = "assistant> "

    _MAX_TOKENS_RETRIES = 3

    async def run(self, user_message: str) -> None:
        self._messages.append({"role": "user", "content": user_message})
        self._trim_conversation_history()

        max_tokens_attempts = 0

        while True:
            message, tool_use_blocks, stop_reason, input_tokens = await stream_chat(
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

            if self._input_token_budget > 0 and input_tokens > self._input_token_budget:
                self._compact_old_tool_results(input_tokens)

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

            tool_results = await self._execute_tools(tool_use_blocks)
            self._messages.append({"role": "user", "content": tool_results})
            self._trim_conversation_history()

            print()  # newline before next spinner

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

    _TRUNCATED_MARKER = "[truncated for context management]"

    def _compact_old_tool_results(self, input_tokens: int) -> None:
        """Truncate old tool-result content strings to reduce input tokens."""
        retention = self._tool_result_retention_chars

        # Find indices of all tool-result messages (role=user, content is a list)
        tool_result_indices = [
            i
            for i, msg in enumerate(self._messages)
            if msg.get("role") == "user" and isinstance(msg.get("content"), list)
        ]

        if len(tool_result_indices) <= 1:
            return  # nothing to compact (keep the most recent one intact)

        # Skip the most recent tool-result message — LLM may still need it
        indices_to_compact = tool_result_indices[:-1]

        compacted = 0
        for idx in indices_to_compact:
            for block in self._messages[idx]["content"]:
                if block.get("type") != "tool_result":
                    continue
                content = block.get("content", "")
                if not isinstance(content, str):
                    continue
                # Skip already-truncated results
                if content.endswith(self._TRUNCATED_MARKER):
                    continue
                if len(content) <= retention:
                    continue
                block["content"] = content[:retention] + f"\n\n{self._TRUNCATED_MARKER}"
                compacted += 1

        if compacted > 0:
            print(
                f"  Note: Compacted {compacted} old tool result(s) — "
                f"input tokens ({input_tokens:,}) exceeded budget ({self._input_token_budget:,})",
                file=sys.stderr,
            )
