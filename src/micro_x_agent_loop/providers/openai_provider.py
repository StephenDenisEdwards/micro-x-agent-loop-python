import json

import openai
from loguru import logger
from tenacity import retry

from micro_x_agent_loop.llm_client import Spinner
from micro_x_agent_loop.providers.common import default_retry_kwargs
from micro_x_agent_loop.tool import Tool

# Map OpenAI finish reasons to Anthropic-style stop reasons.
_STOP_REASON_MAP = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
}


def _to_openai_messages(
    system_prompt: str,
    messages: list[dict],
) -> list[dict]:
    """Convert internal (Anthropic-style) messages to OpenAI chat format."""
    out: list[dict] = []

    if system_prompt:
        out.append({"role": "system", "content": system_prompt})

    for msg in messages:
        role = msg["role"]
        content = msg.get("content", "")

        if role == "assistant":
            if isinstance(content, str):
                out.append({"role": "assistant", "content": content})
                continue

            # Content is a list of blocks
            text_parts: list[str] = []
            tool_calls: list[dict] = []
            for block in content:
                if block.get("type") == "text":
                    text_parts.append(block["text"])
                elif block.get("type") == "tool_use":
                    tool_calls.append({
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block["input"]),
                        },
                    })

            oai_msg: dict = {"role": "assistant"}
            if text_parts:
                oai_msg["content"] = "\n".join(text_parts)
            else:
                oai_msg["content"] = None
            if tool_calls:
                oai_msg["tool_calls"] = tool_calls
            out.append(oai_msg)

        elif role == "user":
            if isinstance(content, str):
                out.append({"role": "user", "content": content})
                continue

            # Content is a list of blocks — may contain tool_result blocks
            text_parts_user: list[str] = []
            for block in content:
                if isinstance(block, str):
                    text_parts_user.append(block)
                elif block.get("type") == "text":
                    text_parts_user.append(block["text"])
                elif block.get("type") == "tool_result":
                    tool_content = block.get("content", "")
                    if isinstance(tool_content, list):
                        tool_content = "\n".join(
                            sub.get("text", "")
                            for sub in tool_content
                            if isinstance(sub, dict) and sub.get("type") == "text"
                        )
                    out.append({
                        "role": "tool",
                        "tool_call_id": block["tool_use_id"],
                        "content": str(tool_content),
                    })

            if text_parts_user:
                out.append({"role": "user", "content": "\n".join(text_parts_user)})

        else:
            # system or other roles — pass through
            out.append({"role": role, "content": content if isinstance(content, str) else str(content)})

    return out


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    """Convert internal (Anthropic-style) tool dicts to OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            },
        }
        for t in tools
    ]


class OpenAIProvider:
    def __init__(self, api_key: str):
        self._client = openai.AsyncOpenAI(api_key=api_key)

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
        openai.RateLimitError,
        openai.APIConnectionError,
        openai.APITimeoutError,
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
    ) -> tuple[dict, list[dict], str]:
        """Stream a chat response from OpenAI, printing text deltas in real time.

        Returns (message_dict, tool_use_blocks, stop_reason) in internal
        (Anthropic-style) format.
        """
        oai_messages = _to_openai_messages(system_prompt, messages)
        oai_tools = _to_openai_tools(tools)

        spinner = Spinner(prefix=line_prefix)
        spinner.start()
        first_output = False

        # Accumulate streamed content
        text_content = ""
        # tool_calls_acc: index -> {"id", "name", "arguments_parts"}
        tool_calls_acc: dict[int, dict] = {}
        finish_reason: str | None = None

        try:
            logger.debug(
                f"API request: model={model}, max_tokens={max_tokens}, "
                f"messages={len(oai_messages)}, tools={len(oai_tools)}"
            )
            kwargs: dict = dict(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=oai_messages,
                stream=True,
            )
            if oai_tools:
                kwargs["tools"] = oai_tools

            stream = await self._client.chat.completions.create(**kwargs)

            async for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                if choice is None:
                    continue

                if choice.finish_reason:
                    finish_reason = choice.finish_reason

                delta = choice.delta
                if delta is None:
                    continue

                # Text content
                if delta.content:
                    if not first_output:
                        spinner.stop()
                        first_output = True
                    print(delta.content, end="", flush=True)
                    text_content += delta.content

                # Tool calls (arrive incrementally by index)
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": tc_delta.id or "",
                                "name": (tc_delta.function.name if tc_delta.function and tc_delta.function.name else ""),
                                "arguments_parts": [],
                            }
                        acc = tool_calls_acc[idx]
                        if tc_delta.id:
                            acc["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                acc["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                acc["arguments_parts"].append(tc_delta.function.arguments)

            if not first_output:
                spinner.stop()

        except BaseException:
            spinner.stop()
            raise

        # Map stop reason
        stop_reason = _STOP_REASON_MAP.get(finish_reason or "stop", "end_turn")

        # Build internal-format content blocks
        assistant_content: list[dict] = []
        tool_use_blocks: list[dict] = []

        if text_content:
            assistant_content.append({"type": "text", "text": text_content})

        for idx in sorted(tool_calls_acc):
            acc = tool_calls_acc[idx]
            raw_args = "".join(acc["arguments_parts"])
            try:
                parsed_input = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse tool call arguments: {raw_args[:200]}")
                parsed_input = {}
            tool_block = {
                "type": "tool_use",
                "id": acc["id"],
                "name": acc["name"],
                "input": parsed_input,
            }
            assistant_content.append(tool_block)
            tool_use_blocks.append(tool_block)

        logger.debug(
            f"API response: stop_reason={stop_reason}, "
            f"text_len={len(text_content)}, tool_calls={len(tool_use_blocks)}"
        )

        message = {"role": "assistant", "content": assistant_content}
        return message, tool_use_blocks, stop_reason

    @retry(**default_retry_kwargs((
        openai.RateLimitError,
        openai.APIConnectionError,
        openai.APITimeoutError,
    )))
    async def create_message(
        self,
        model: str,
        max_tokens: int,
        temperature: float,
        messages: list[dict],
    ) -> str:
        """Non-streaming message creation (used for compaction/summarization)."""
        oai_messages = _to_openai_messages("", messages)
        logger.debug(f"Compaction API request: model={model}, messages={len(oai_messages)}")
        response = await self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=oai_messages,
        )
        text = response.choices[0].message.content or ""
        logger.debug(f"Compaction API response: len={len(text)}")
        return text
