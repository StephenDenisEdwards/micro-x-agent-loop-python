from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

import openai
from loguru import logger
from tenacity import retry

from micro_x_agent_loop.providers.common import default_retry_kwargs
from micro_x_agent_loop.tool import Tool, canonicalise_tools
from micro_x_agent_loop.usage import UsageResult

if TYPE_CHECKING:
    from micro_x_agent_loop.agent_channel import AgentChannel

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
    def __init__(self, api_key: str, *, base_url: str | None = None, provider_name: str = "openai"):
        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._provider_name = provider_name

    def _extract_cached_tokens(self, usage: Any) -> int:
        """Extract cache-hit token count from a usage object. Override in subclasses."""
        details = getattr(usage, "prompt_tokens_details", None)
        if details is not None:
            return getattr(details, "cached_tokens", 0) or 0
        return 0

    def convert_tools(self, tools: list[Tool]) -> list[dict]:
        return canonicalise_tools(tools)

    def _build_stream_kwargs(
        self,
        model: str,
        max_tokens: int,
        temperature: float,
        messages: list[dict],
        tools: list[dict],
    ) -> dict:
        """Build kwargs for the streaming chat completions call.

        Subclasses can override to adjust parameters for provider-specific
        compatibility (e.g. removing ``stream_options`` for Ollama).
        """
        kwargs: dict = dict(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
        )
        if tools:
            kwargs["tools"] = tools
        return kwargs

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
        channel: AgentChannel | None = None,
    ) -> tuple[dict, list[dict], str, UsageResult]:
        """Stream a chat response from OpenAI, emitting text deltas via AgentChannel.

        Returns (message_dict, tool_use_blocks, stop_reason, usage) in internal
        (Anthropic-style) format.
        """
        oai_messages = _to_openai_messages(system_prompt, messages)
        oai_tools = _to_openai_tools(tools)

        t_start = time.monotonic()
        t_first_token: float | None = None

        # Accumulate streamed content
        text_content = ""
        # tool_calls_acc: index -> {"id", "name", "arguments_parts"}
        tool_calls_acc: dict[int, dict] = {}
        finish_reason: str | None = None

        # Track usage from the final chunk
        prompt_tokens = 0
        completion_tokens = 0
        cached_tokens = 0

        try:
            logger.debug(
                f"API request: model={model}, max_tokens={max_tokens}, "
                f"messages={len(oai_messages)}, tools={len(oai_tools)}"
            )
            kwargs = self._build_stream_kwargs(
                model, max_tokens, temperature, oai_messages, oai_tools,
            )

            stream = await self._client.chat.completions.create(**kwargs)

            async for chunk in stream:
                # Handle usage-only chunk (final chunk with stream_options)
                if chunk.usage is not None:
                    prompt_tokens = chunk.usage.prompt_tokens
                    completion_tokens = chunk.usage.completion_tokens
                    cached_tokens = self._extract_cached_tokens(chunk.usage)

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
                    if t_first_token is None:
                        t_first_token = time.monotonic()
                    if channel is not None:
                        channel.emit_text_delta(delta.content)
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

        except BaseException:
            raise

        t_end = time.monotonic()

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

        usage_result = UsageResult(
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            cache_read_input_tokens=cached_tokens,
            duration_ms=(t_end - t_start) * 1000,
            time_to_first_token_ms=((t_first_token - t_start) * 1000) if t_first_token else 0.0,
            provider=self._provider_name,
            model=model,
            message_count=len(messages),
            tool_schema_count=len(tools),
            stop_reason=stop_reason,
        )

        return message, tool_use_blocks, stop_reason, usage_result

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
    ) -> tuple[str, UsageResult]:
        """Non-streaming message creation (used for compaction/summarization)."""
        oai_messages = _to_openai_messages("", messages)
        t_start = time.monotonic()
        logger.debug(f"Compaction API request: model={model}, messages={len(oai_messages)}")
        response = await self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=oai_messages,
        )
        t_end = time.monotonic()
        text = response.choices[0].message.content or ""

        resp_usage = response.usage
        p_tokens = resp_usage.prompt_tokens if resp_usage else 0
        c_tokens = resp_usage.completion_tokens if resp_usage else 0
        c_cached = self._extract_cached_tokens(resp_usage) if resp_usage else 0

        logger.debug(f"Compaction API response: len={len(text)}")

        usage_result = UsageResult(
            input_tokens=p_tokens,
            output_tokens=c_tokens,
            cache_read_input_tokens=c_cached,
            duration_ms=(t_end - t_start) * 1000,
            provider=self._provider_name,
            model=model,
            message_count=len(messages),
        )

        return text, usage_result
