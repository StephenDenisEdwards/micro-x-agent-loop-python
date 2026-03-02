from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from loguru import logger

from micro_x_agent_loop.api_payload_store import ApiPayload, ApiPayloadStore
from micro_x_agent_loop.llm_client import Spinner
from micro_x_agent_loop.usage import UsageResult, estimate_cost
from micro_x_agent_loop.system_prompt import resolve_system_prompt
from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.tool_result_formatter import ToolResultFormatter
from micro_x_agent_loop.turn_events import TurnEvents


class TurnEngine:
    def __init__(
        self,
        *,
        provider: Any,
        model: str,
        max_tokens: int,
        temperature: float,
        system_prompt: str,
        converted_tools: list[dict],
        tool_map: dict[str, Tool],
        line_prefix: str,
        max_tool_result_chars: int,
        max_tokens_retries: int,
        events: TurnEvents,
        summarization_provider: Any | None = None,
        summarization_model: str = "",
        summarization_enabled: bool = False,
        summarization_threshold: int = 4000,
        formatter: ToolResultFormatter | None = None,
        api_payload_store: ApiPayloadStore | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._system_prompt_template = system_prompt
        self._converted_tools = converted_tools
        self._tool_map = tool_map
        self._line_prefix = line_prefix
        self._max_tool_result_chars = max_tool_result_chars
        self._max_tokens_retries = max_tokens_retries
        self._events = events
        self._summarization_provider = summarization_provider
        self._summarization_model = summarization_model
        self._summarization_enabled = summarization_enabled
        self._summarization_threshold = summarization_threshold
        self._formatter = formatter or ToolResultFormatter()
        self._api_payload_store = api_payload_store

    async def run(
        self,
        *,
        messages: list[dict],
        user_message: str,
    ) -> tuple[str | None, str | None]:
        last_assistant_message_id: str | None = None
        current_user_message_id = self._events.on_append_message("user", user_message)
        self._events.on_user_message_appended(current_user_message_id)
        await self._events.on_maybe_compact()

        max_tokens_attempts = 0

        while True:
            system_prompt = resolve_system_prompt(self._system_prompt_template)
            message, tool_use_blocks, stop_reason, usage = await self._provider.stream_chat(
                self._model,
                self._max_tokens,
                self._temperature,
                system_prompt,
                messages,
                self._converted_tools,
                line_prefix=self._line_prefix,
            )

            self._events.on_api_call_completed(usage, "main")

            if self._api_payload_store is not None:
                self._record_api_payload(
                    system_prompt, messages, message, stop_reason, usage,
                )

            last_assistant_message_id = self._events.on_append_message("assistant", message["content"])

            if stop_reason == "max_tokens" and not tool_use_blocks:
                max_tokens_attempts += 1
                if max_tokens_attempts >= self._max_tokens_retries:
                    print(
                        f"\n{self._line_prefix}[Stopped: response exceeded max_tokens "
                        f"({self._max_tokens}) {self._max_tokens_retries} times in a row. "
                        f"Try increasing MaxTokens in config.json or simplifying the request.]",
                    )
                    return current_user_message_id, last_assistant_message_id
                self._events.on_append_message(
                    "user",
                    (
                        "Your response was cut off because it exceeded the token limit. "
                        "Please continue, but be more concise. If you were writing a file, "
                        "break it into smaller sections or shorten the content."
                    ),
                )
                print()
                continue

            max_tokens_attempts = 0

            if not tool_use_blocks:
                return current_user_message_id, last_assistant_message_id

            tool_names = ", ".join(b["name"] for b in tool_use_blocks)
            spinner = Spinner(prefix=self._line_prefix, label=f" Running {tool_names}...")
            spinner.start()
            try:
                self._events.on_ensure_checkpoint_for_turn(tool_use_blocks)
                tool_results = await self.execute_tools(
                    tool_use_blocks, last_assistant_message_id=last_assistant_message_id
                )
            finally:
                spinner.stop()
            self._events.on_append_message("user", tool_results)
            await self._events.on_maybe_compact()
            print()

    async def execute_tools(self, tool_use_blocks: list[dict], *, last_assistant_message_id: str | None) -> list[dict]:
        async def run_one(block: dict) -> dict:
            tool_name = block["name"]
            tool_use_id = block["id"]
            tool = self._tool_map.get(tool_name)
            tool_input = block["input"]

            self._events.on_tool_started(tool_use_id, tool_name)

            if tool is None:
                content = f'Error: unknown tool "{tool_name}"'
                self._events.on_record_tool_call(
                    tool_call_id=tool_use_id,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    result_text=content,
                    is_error=True,
                    message_id=last_assistant_message_id,
                )
                self._events.on_tool_completed(tool_use_id, tool_name, True)
                self._events.on_tool_executed(tool_name, len(content), 0.0, True)
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                    "is_error": True,
                }

            t_start = time.monotonic()
            try:
                self._events.on_maybe_track_mutation(tool_name, tool, tool_input)
                tool_result = await tool.execute(tool_input)
                self._track_nested_llm_usage(tool_name, tool_result.structured)
                if tool_result.is_error:
                    raise RuntimeError(tool_result.text)
                formatted = self._formatter.format(tool_name, tool_result.text, tool_result.structured)
                result_text = self._truncate_tool_result(formatted, tool_name)
                result_text, was_summarized = await self._summarize_tool_result(result_text, tool_name)
                t_end = time.monotonic()
                duration_ms = (t_end - t_start) * 1000
                self._events.on_record_tool_call(
                    tool_call_id=tool_use_id,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    result_text=result_text,
                    is_error=False,
                    message_id=last_assistant_message_id,
                )
                self._events.on_tool_completed(tool_use_id, tool_name, False)
                self._events.on_tool_executed(
                    tool_name, len(result_text), duration_ms, False,
                    was_summarized=was_summarized,
                )
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result_text,
                }
            except Exception as ex:
                t_end = time.monotonic()
                duration_ms = (t_end - t_start) * 1000
                content = f'Error executing tool "{tool_name}": {ex}'
                self._events.on_record_tool_call(
                    tool_call_id=tool_use_id,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    result_text=content,
                    is_error=True,
                    message_id=last_assistant_message_id,
                )
                self._events.on_tool_completed(tool_use_id, tool_name, True)
                self._events.on_tool_executed(tool_name, len(content), duration_ms, True)
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                    "is_error": True,
                }

        return list(await asyncio.gather(*(run_one(b) for b in tool_use_blocks)))

    async def _summarize_tool_result(self, result: str, tool_name: str) -> tuple[str, bool]:
        """Summarize a large tool result using a cheaper model.

        Returns (possibly-summarized result, was_summarized).
        """
        if (
            not self._summarization_enabled
            or self._summarization_provider is None
            or len(result) <= self._summarization_threshold
        ):
            return result, False

        prompt = (
            "Summarize this tool output concisely, preserving all decision-relevant "
            "data (names, numbers, IDs, paths, errors). "
            f"Tool: {tool_name}\n\n{result}"
        )
        try:
            summary, usage = await self._summarization_provider.create_message(
                self._summarization_model,
                2048,
                0,
                [{"role": "user", "content": prompt}],
            )
            self._events.on_api_call_completed(usage, "tool_summarization")
            logger.info(
                f"Summarized {tool_name} result: {len(result):,} chars -> {len(summary):,} chars"
            )
            return summary, True
        except Exception as ex:
            logger.warning(f"Tool result summarization failed for {tool_name}: {ex}")
            return result, False

    def _track_nested_llm_usage(self, tool_name: str, structured: Any) -> None:
        """Track LLM usage reported by an MCP tool in its structured result."""
        if not isinstance(structured, dict):
            return
        input_tokens = structured.get("input_tokens")
        output_tokens = structured.get("output_tokens")
        model = structured.get("model")
        if input_tokens is None or output_tokens is None or model is None:
            return
        usage = UsageResult(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider=structured.get("provider", "anthropic"),
            model=model,
        )
        self._events.on_api_call_completed(usage, f"nested:{tool_name}")

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

    def _record_api_payload(
        self,
        system_prompt: str,
        messages: list[dict],
        response_message: dict,
        stop_reason: str,
        usage: Any,
    ) -> None:
        payload = ApiPayload(
            timestamp=time.time(),
            model=self._model,
            system_prompt=system_prompt,
            messages=list(messages),
            tools_count=len(self._converted_tools),
            response_message=response_message,
            stop_reason=stop_reason,
            usage=usage,
        )
        self._api_payload_store.record(payload)
        try:
            log_data = {
                "timestamp": payload.timestamp,
                "model": payload.model,
                "system_prompt_chars": len(payload.system_prompt),
                "messages_count": len(payload.messages),
                "tools_count": payload.tools_count,
                "stop_reason": payload.stop_reason,
                "response_message": payload.response_message,
                "usage": {
                    "input_tokens": usage.input_tokens if usage else 0,
                    "output_tokens": usage.output_tokens if usage else 0,
                    "cache_read_input_tokens": usage.cache_read_input_tokens if usage else 0,
                    "cache_creation_input_tokens": usage.cache_creation_input_tokens if usage else 0,
                    "cost_usd": round(estimate_cost(usage), 6) if usage else 0,
                },
                "system_prompt": payload.system_prompt,
                "messages": payload.messages,
            }
            logger.bind(api_payload=True).debug(json.dumps(log_data, default=str))
        except Exception:
            pass
