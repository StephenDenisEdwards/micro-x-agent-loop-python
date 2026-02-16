import asyncio
import sys

import anthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)
import logging

from micro_x_agent_loop.tool import Tool

logger = logging.getLogger(__name__)

_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


async def _run_spinner(stop: asyncio.Event) -> None:
    """Show a spinner animation until stop is set."""
    label = " Thinking..."
    width = 1 + len(label)
    i = 0
    while not stop.is_set():
        frame = _SPINNER[i % len(_SPINNER)] + label
        sys.stdout.write(frame)
        sys.stdout.flush()
        await asyncio.sleep(0.08)
        sys.stdout.write("\b" * width + " " * width + "\b" * width)
        sys.stdout.flush()
        i += 1


def create_client(api_key: str) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=api_key)


def to_anthropic_tools(tools: list[Tool]) -> list[dict]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in tools
    ]


def _on_retry(retry_state):
    attempt = retry_state.attempt_number
    wait = retry_state.next_action.sleep if retry_state.next_action else 0
    print(
        f"Rate limited. Retrying in {wait:.0f}s (attempt {attempt}/5)...",
        file=sys.stderr,
    )


@retry(
    retry=retry_if_exception_type(anthropic.RateLimitError),
    wait=wait_exponential(multiplier=10, min=10, max=320),
    stop=stop_after_attempt(5),
    before_sleep=_on_retry,
    reraise=True,
)
async def stream_chat(
    client: anthropic.AsyncAnthropic,
    model: str,
    max_tokens: int,
    temperature: float,
    system_prompt: str,
    messages: list[dict],
    tools: list[dict],
) -> tuple[dict, list[dict]]:
    """Stream a chat response, printing text deltas to stdout in real time.

    Returns the assembled message dict and any tool_use blocks found.
    """
    tool_use_blocks = []

    spinner_stop = asyncio.Event()
    spinner_task = asyncio.create_task(_run_spinner(spinner_stop))
    first_output = False

    async with client.messages.stream(
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
                        spinner_stop.set()
                        await spinner_task
                        first_output = True
                    print(event.delta.text, end="", flush=True)

        if not first_output:
            spinner_stop.set()
            await spinner_task

        # Get the final assembled message
        response = await stream.get_final_message()

    # Build content and extract tool_use blocks
    assistant_content = []
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
    return message, tool_use_blocks
