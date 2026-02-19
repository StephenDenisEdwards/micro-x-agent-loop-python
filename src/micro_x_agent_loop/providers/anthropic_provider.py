import anthropic
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from micro_x_agent_loop.llm_client import Spinner, _on_retry
from micro_x_agent_loop.tool import Tool


class AnthropicProvider:
    def __init__(self, api_key: str):
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    def convert_tools(self, tools: list[Tool]) -> list[dict]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]

    @retry(
        retry=retry_if_exception_type((
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
        )),
        wait=wait_exponential(multiplier=10, min=10, max=320),
        stop=stop_after_attempt(5),
        before_sleep=_on_retry,
        reraise=True,
    )
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
    ) -> tuple[dict, list[dict], str]:
        """Stream a chat response, printing text deltas to stdout in real time.

        Returns (message dict, tool_use blocks, stop_reason).
        """
        tool_use_blocks: list[dict] = []

        spinner = Spinner(prefix=line_prefix)
        spinner.start()
        first_output = False

        try:
            logger.debug(
                f"API request: model={model}, max_tokens={max_tokens}, "
                f"messages={len(messages)}, tools={len(tools)}"
            )
            async with self._client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=messages,
                tools=tools,
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            if not first_output:
                                spinner.stop()
                                first_output = True
                            print(event.delta.text, end="", flush=True)

                if not first_output:
                    spinner.stop()

                response = await stream.get_final_message()
        except BaseException:
            spinner.stop()
            raise

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
        return message, tool_use_blocks, response.stop_reason

    @retry(
        retry=retry_if_exception_type((
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
        )),
        wait=wait_exponential(multiplier=10, min=10, max=320),
        stop=stop_after_attempt(5),
        before_sleep=_on_retry,
        reraise=True,
    )
    async def create_message(
        self,
        model: str,
        max_tokens: int,
        temperature: float,
        messages: list[dict],
    ) -> str:
        """Non-streaming message creation (used for compaction/summarization)."""
        logger.debug(f"Compaction API request: model={model}, messages={len(messages)}")
        response = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages,
        )
        usage = response.usage
        logger.debug(
            f"Compaction API response: input_tokens={usage.input_tokens}, "
            f"output_tokens={usage.output_tokens}"
        )
        return response.content[0].text
