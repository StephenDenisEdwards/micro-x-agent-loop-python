from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any

from loguru import logger

from micro_x_agent_loop.tool import Tool, canonicalise_tools
from micro_x_agent_loop.usage import UsageResult

if TYPE_CHECKING:
    from micro_x_agent_loop.agent_channel import AgentChannel

# Map Gemini finish reasons to internal (Anthropic-style) stop reasons.
_STOP_REASON_MAP = {
    "STOP": "end_turn",
    "MAX_TOKENS": "max_tokens",
    "FINISH_REASON_UNSPECIFIED": "end_turn",
    "OTHER": "end_turn",
}


def _build_tool_use_id_map(messages: list[dict]) -> dict[str, str]:
    """Return a mapping of tool_use_id → tool_name from all assistant messages."""
    id_to_name: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                id_to_name[block["id"]] = block["name"]
    return id_to_name


def _to_gemini_contents(messages: list[dict]) -> list[Any]:
    """Convert internal (Anthropic-style) messages to Gemini Content objects."""
    from google.genai import types

    id_to_name = _build_tool_use_id_map(messages)
    contents: list[Any] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "assistant":
            parts: list[Any] = []
            blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        parts.append(types.Part(text=text))
                elif block.get("type") == "tool_use":
                    parts.append(types.Part(
                        function_call=types.FunctionCall(
                            name=block["name"],
                            args=block.get("input", {}),
                        )
                    ))
            if parts:
                contents.append(types.Content(role="model", parts=parts))

        elif role == "user":
            parts = []
            if isinstance(content, str):
                if content:
                    parts.append(types.Part(text=content))
            else:
                text_parts: list[str] = []
                tool_result_parts: list[Any] = []
                for block in content:
                    if isinstance(block, str):
                        text_parts.append(block)
                    elif isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_result":
                            tool_use_id = block.get("tool_use_id", "")
                            tool_name = id_to_name.get(tool_use_id, tool_use_id)
                            tool_content = block.get("content", "")
                            if isinstance(tool_content, list):
                                tool_content = "\n".join(
                                    sub.get("text", "")
                                    for sub in tool_content
                                    if isinstance(sub, dict) and sub.get("type") == "text"
                                )
                            tool_result_parts.append(types.Part(
                                function_response=types.FunctionResponse(
                                    name=tool_name,
                                    response={"result": str(tool_content)},
                                )
                            ))
                if text_parts:
                    combined = "\n".join(t for t in text_parts if t)
                    if combined:
                        parts.append(types.Part(text=combined))
                parts.extend(tool_result_parts)
            if parts:
                contents.append(types.Content(role="user", parts=parts))

    return contents


def _to_gemini_tools(tools: list[dict]) -> list[Any] | None:
    """Convert canonical tool dicts to a Gemini Tool object."""
    if not tools:
        return None
    from google.genai import types

    declarations = [
        types.FunctionDeclaration(
            name=t["name"],
            description=t.get("description", ""),
            parameters=t.get("input_schema", {}),
        )
        for t in tools
    ]
    return [types.Tool(function_declarations=declarations)]


class GeminiProvider:
    """Google Gemini provider using the google-genai SDK."""

    def __init__(self, api_key: str) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)

    def convert_tools(self, tools: list[Tool]) -> list[dict]:
        return canonicalise_tools(tools)

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
        """Stream a chat response from Gemini, emitting text deltas via AgentChannel.

        Returns (message_dict, tool_use_blocks, stop_reason, usage) in internal
        (Anthropic-style) format.
        """
        from google.genai import types

        contents = _to_gemini_contents(messages)
        gemini_tools = _to_gemini_tools(tools)

        config_kwargs: dict[str, Any] = {
            "max_output_tokens": max_tokens,
            "temperature": temperature,
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
        }
        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt
        if gemini_tools:
            config_kwargs["tools"] = gemini_tools

        config = types.GenerateContentConfig(**config_kwargs)

        logger.debug(
            f"Gemini API request: model={model}, max_tokens={max_tokens}, "
            f"messages={len(messages)}, tools={len(tools)}"
        )

        t_start = time.monotonic()
        t_first_token: float | None = None

        text_content = ""
        tool_use_blocks: list[dict] = []
        finish_reason: str | None = None
        usage_meta: Any = None

        async for chunk in await self._client.aio.models.generate_content_stream(
            model=model,
            contents=contents,
            config=config,
        ):
            # Text delta
            if chunk.text:
                if t_first_token is None:
                    t_first_token = time.monotonic()
                if channel is not None:
                    channel.emit_text_delta(chunk.text)
                text_content += chunk.text

            # Function calls (complete objects, not streamed incrementally)
            if chunk.function_calls:
                for fc in chunk.function_calls:
                    tool_use_blocks.append({
                        "type": "tool_use",
                        "id": str(uuid.uuid4()),
                        "name": fc.name,
                        "input": dict(fc.args) if fc.args else {},
                    })

            # Finish reason (from candidates)
            if chunk.candidates:
                candidate = chunk.candidates[0]
                fr = getattr(candidate, "finish_reason", None)
                if fr is not None:
                    finish_reason = str(fr.name) if hasattr(fr, "name") else str(fr)

            # Usage (typically on the final chunk)
            if chunk.usage_metadata:
                usage_meta = chunk.usage_metadata

        t_end = time.monotonic()

        # Determine stop reason
        if tool_use_blocks:
            stop_reason = "tool_use"
        else:
            stop_reason = _STOP_REASON_MAP.get(finish_reason or "STOP", "end_turn")

        # Build internal-format message
        assistant_content: list[dict] = []
        if text_content:
            assistant_content.append({"type": "text", "text": text_content})
        assistant_content.extend(tool_use_blocks)
        message = {"role": "assistant", "content": assistant_content}

        # Extract usage
        input_tokens = getattr(usage_meta, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage_meta, "candidates_token_count", 0) or 0
        cached_tokens = getattr(usage_meta, "cached_content_token_count", 0) or 0

        logger.debug(
            f"Gemini API response: stop_reason={stop_reason}, "
            f"input_tokens={input_tokens}, output_tokens={output_tokens}, "
            f"cached_tokens={cached_tokens}"
        )

        usage_result = UsageResult(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cached_tokens,
            duration_ms=(t_end - t_start) * 1000,
            time_to_first_token_ms=((t_first_token - t_start) * 1000) if t_first_token else 0.0,
            provider="gemini",
            model=model,
            message_count=len(messages),
            tool_schema_count=len(tools),
            stop_reason=stop_reason,
        )

        return message, tool_use_blocks, stop_reason, usage_result

    async def create_message(
        self,
        model: str,
        max_tokens: int,
        temperature: float,
        messages: list[dict],
    ) -> tuple[str, UsageResult]:
        """Non-streaming message creation (used for compaction/summarization)."""
        from google.genai import types

        contents = _to_gemini_contents(messages)
        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
        )

        t_start = time.monotonic()
        logger.debug(f"Gemini compaction request: model={model}, messages={len(messages)}")

        response = await self._client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

        t_end = time.monotonic()
        text = response.text or ""

        usage_meta = response.usage_metadata
        input_tokens = getattr(usage_meta, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage_meta, "candidates_token_count", 0) or 0
        cached_tokens = getattr(usage_meta, "cached_content_token_count", 0) or 0

        logger.debug(f"Gemini compaction response: len={len(text)}")

        usage_result = UsageResult(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cached_tokens,
            duration_ms=(t_end - t_start) * 1000,
            provider="gemini",
            model=model,
            message_count=len(messages),
        )

        return text, usage_result
