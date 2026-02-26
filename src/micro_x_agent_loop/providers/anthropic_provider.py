import time

import anthropic
from loguru import logger
from tenacity import retry

from micro_x_agent_loop.llm_client import Spinner
from micro_x_agent_loop.providers.common import default_retry_kwargs
from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.usage import UsageResult


class AnthropicProvider:
    def __init__(self, api_key: str, *, prompt_caching_enabled: bool = False):
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._prompt_caching_enabled = prompt_caching_enabled

    def convert_tools(self, tools: list[Tool]) -> list[dict]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]

    @retry(**default_retry_kwargs((
        anthropic.RateLimitError,
        anthropic.APIConnectionError,
        anthropic.APITimeoutError,
    )))
    async def stream_chat(
        self,
        model: str,
        max_tokens: int,
        temperature: float,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        *,
        line_prefix: str = "",
    ) -> tuple[dict, list[dict], str, UsageResult]:
        """Stream a chat response, printing text deltas to stdout in real time.

        Returns (message dict, tool_use blocks, stop_reason, usage).
        """
        tool_use_blocks: list[dict] = []

        spinner = Spinner(prefix=line_prefix)
        spinner.start()
        first_output = False

        t_start = time.monotonic()
        t_first_token: float | None = None

        try:
            # Prompt caching: wrap system prompt and tag last tool
            if self._prompt_caching_enabled:
                api_system = [
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
                if tools:
                    api_tools = [*tools]
                    api_tools[-1] = {**api_tools[-1], "cache_control": {"type": "ephemeral"}}
                else:
                    api_tools = tools
            else:
                api_system = system_prompt
                api_tools = tools

            logger.debug(
                f"API request: model={model}, max_tokens={max_tokens}, "
                f"messages={len(messages)}, tools={len(tools)}, "
                f"prompt_caching={self._prompt_caching_enabled}"
            )
            async with self._client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=api_system,
                messages=messages,
                tools=api_tools,
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            if not first_output:
                                spinner.stop()
                                first_output = True
                                t_first_token = time.monotonic()
                            print(event.delta.text, end="", flush=True)

                if not first_output:
                    spinner.stop()

                response = await stream.get_final_message()
        except BaseException:
            spinner.stop()
            raise

        t_end = time.monotonic()
        usage = response.usage
        logger.debug(
            f"API response: stop_reason={response.stop_reason}, "
            f"input_tokens={usage.input_tokens}, output_tokens={usage.output_tokens}"
        )

        assistant_content: list[dict] = []
        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                tool_block = {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
                assistant_content.append(tool_block)
                tool_use_blocks.append(tool_block)

        message = {"role": "assistant", "content": assistant_content}

        usage_result = UsageResult(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            duration_ms=(t_end - t_start) * 1000,
            time_to_first_token_ms=((t_first_token - t_start) * 1000) if t_first_token else 0.0,
            provider="anthropic",
            model=model,
            message_count=len(messages),
            tool_schema_count=len(tools),
            stop_reason=response.stop_reason,
        )

        return message, tool_use_blocks, response.stop_reason, usage_result

    @retry(**default_retry_kwargs((
        anthropic.RateLimitError,
        anthropic.APIConnectionError,
        anthropic.APITimeoutError,
    )))
    async def create_message(
        self,
        model: str,
        max_tokens: int,
        temperature: float,
        messages: list[dict],
    ) -> tuple[str, UsageResult]:
        """Non-streaming message creation (used for compaction/summarization)."""
        t_start = time.monotonic()
        logger.debug(f"Compaction API request: model={model}, messages={len(messages)}")
        response = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages,
        )
        t_end = time.monotonic()
        usage = response.usage
        logger.debug(
            f"Compaction API response: input_tokens={usage.input_tokens}, "
            f"output_tokens={usage.output_tokens}"
        )

        usage_result = UsageResult(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            duration_ms=(t_end - t_start) * 1000,
            provider="anthropic",
            model=model,
            message_count=len(messages),
        )

        return response.content[0].text, usage_result
