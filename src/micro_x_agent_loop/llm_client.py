import asyncio
import sys
import threading

import anthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from loguru import logger

from micro_x_agent_loop.tool import Tool

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class Spinner:
    """Thread-based spinner that renders on the current line using \\r."""

    def __init__(self, prefix: str = "", label: str = " Thinking..."):
        self._prefix = prefix
        self._label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame_width = 1 + len(label)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        if self._thread:
            self._thread.join()
        # Clear spinner text: overwrite with spaces, then reposition cursor after prefix
        clear = self._prefix + " " * self._frame_width
        sys.stdout.write("\r" + clear + "\r" + self._prefix)
        sys.stdout.flush()

    def _run(self) -> None:
        i = 0
        try:
            while not self._stop.is_set():
                frame = _SPINNER_FRAMES[i % len(_SPINNER_FRAMES)] + self._label
                sys.stdout.write("\r" + self._prefix + frame)
                sys.stdout.flush()
                self._stop.wait(0.08)
                i += 1
        except (UnicodeEncodeError, OSError):
            pass  # Terminal doesn't support these characters; fail silently


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
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    reason = type(exc).__name__ if exc else "Unknown"
    logger.warning(f"{reason}. Retrying in {wait:.0f}s (attempt {attempt}/5)...")


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
    client: anthropic.AsyncAnthropic,
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
    tool_use_blocks = []

    spinner = Spinner(prefix=line_prefix)
    spinner.start()
    first_output = False

    try:
        logger.debug(f"API request: model={model}, max_tokens={max_tokens}, messages={len(messages)}, tools={len(tools)}")
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
                            spinner.stop()
                            first_output = True
                        print(event.delta.text, end="", flush=True)

            if not first_output:
                spinner.stop()

            # Get the final assembled message
            response = await stream.get_final_message()
    except BaseException:
        spinner.stop()
        raise

    usage = response.usage
    logger.debug(f"API response: stop_reason={response.stop_reason}, input_tokens={usage.input_tokens}, output_tokens={usage.output_tokens}")

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
    return message, tool_use_blocks, response.stop_reason
