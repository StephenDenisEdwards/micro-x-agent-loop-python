"""ToolDispatcher — routes a turn's tool_use blocks to pseudo handlers
or regular MCP tools and merges results in original block order.

Extracted from ``TurnEngine`` so the main turn loop can focus on LLM I/O,
routing, and turn lifecycle. Owns the pseudo-tool registry, the MCP tool
map, and tool-result formatting/truncation/summarization.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

from micro_x_agent_loop.provider import LLMCompactor
from micro_x_agent_loop.pseudo_tool_handlers import (
    PseudoToolHandler,
    PseudoToolRegistry,
)
from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.tool_result_formatter import ToolResultFormatter
from micro_x_agent_loop.turn_events import TurnEvents
from micro_x_agent_loop.usage import UsageResult

if TYPE_CHECKING:
    from micro_x_agent_loop.agent_channel import AgentChannel
    from micro_x_agent_loop.app_config import ToolResultOverride


@dataclass(frozen=True)
class DispatchResult:
    """Outcome of dispatching one batch of tool_use blocks.

    ``results`` are merged in the original block order — the model expects
    each ``tool_use_id`` to be answered, in order. ``ran_regular_tools`` is
    True when at least one block hit a real MCP tool (vs. only pseudo-tools
    like ``ask_user`` / ``spawn_subagent`` / ``task_*``); the caller uses
    this to decide whether to trigger conversation compaction after the
    turn.
    """

    results: list[dict]
    ran_regular_tools: bool


class ToolDispatcher:
    """Routes tool_use blocks to pseudo handlers or MCP execution."""

    def __init__(
        self,
        *,
        pseudo_registry: PseudoToolRegistry,
        tool_map: dict[str, Tool],
        events: TurnEvents,
        channel: AgentChannel | None,
        formatter: ToolResultFormatter,
        max_tool_result_chars: int,
        summarization_provider: LLMCompactor | None,
        summarization_model: str,
        summarization_enabled: bool,
        summarization_threshold: int,
        tool_result_overrides: dict[str, ToolResultOverride],
    ) -> None:
        self._pseudo_registry = pseudo_registry
        self._tool_map = tool_map
        self._events = events
        self._channel = channel
        self._formatter = formatter
        self._max_tool_result_chars = max_tool_result_chars
        self._summarization_provider = summarization_provider
        self._summarization_model = summarization_model
        self._summarization_enabled = summarization_enabled
        self._summarization_threshold = summarization_threshold
        self._tool_result_overrides = tool_result_overrides

    async def dispatch(
        self,
        tool_use_blocks: list[dict],
        *,
        last_assistant_message_id: str | None,
    ) -> DispatchResult:
        """Split blocks into pseudo + regular, execute both, merge in order."""
        grouped: dict[int, tuple[PseudoToolHandler, list[dict]]] = {}
        regular_blocks: list[dict] = []
        for block in tool_use_blocks:
            handler = self._pseudo_registry.get(block["name"])
            if handler is None:
                regular_blocks.append(block)
            else:
                key = id(handler)
                if key not in grouped:
                    grouped[key] = (handler, [])
                grouped[key][1].append(block)

        inline_results: list[dict] = []
        for handler, handler_blocks in grouped.values():
            inline_results.extend(await handler.execute_batch(handler_blocks))

        if not regular_blocks:
            return DispatchResult(results=inline_results, ran_regular_tools=False)

        self._events.on_ensure_checkpoint_for_turn(regular_blocks)
        regular_results = await self.execute_tools(
            regular_blocks, last_assistant_message_id=last_assistant_message_id
        )
        if inline_results:
            merged = self._merge_tool_results(tool_use_blocks, inline_results, regular_results)
            return DispatchResult(results=merged, ran_regular_tools=True)
        return DispatchResult(results=regular_results, ran_regular_tools=True)

    async def execute_tools(
        self,
        tool_use_blocks: list[dict],
        *,
        last_assistant_message_id: str | None,
    ) -> list[dict]:
        async def run_one(block: dict) -> dict:
            tool_name = block["name"]
            tool_use_id = block["id"]
            tool = self._tool_map.get(tool_name)
            tool_input = block["input"]

            self._events.on_tool_started(tool_use_id, tool_name)
            if self._channel is not None:
                self._channel.emit_tool_started(tool_use_id, tool_name, tool_input=tool_input)

            if tool is None:
                available = sorted(self._tool_map.keys())
                content = (
                    f'Error: unknown tool "{tool_name}". '
                    f'Available tools: {", ".join(available)}'
                )
                # `gemma_unparsed.hallucinated_name` counter — small models
                # (e.g. gemma3:4b) invoke tool names that aren't in the
                # registry. Surfaced as a structured warning so operators can
                # see the rate without needing a full metrics sink.
                logger.warning(
                    "gemma_unparsed.hallucinated_name tool={tool!r} available_count={n}",
                    tool=tool_name,
                    n=len(available),
                )
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
                if self._channel is not None:
                    self._channel.emit_tool_completed(
                        tool_use_id, tool_name, True,
                        result_chars=len(content),
                    )
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
                summarize, threshold, max_chars = self._resolve_tool_result_overrides(tool_name)
                result_text, was_truncated = self._truncate_tool_result(formatted, tool_name, max_chars)
                result_text, was_summarized = await self._summarize_tool_result(
                    result_text, tool_name, summarize, threshold
                )
                t_end = time.monotonic()
                duration_ms = (t_end - t_start) * 1000
                self._events.on_record_tool_call(
                    tool_call_id=tool_use_id,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    result_text=result_text,
                    is_error=False,
                    message_id=last_assistant_message_id,
                    was_truncated=was_truncated,
                    original_chars=len(formatted),
                )
                self._events.on_tool_completed(tool_use_id, tool_name, False)
                self._events.on_tool_executed(
                    tool_name,
                    len(result_text),
                    duration_ms,
                    False,
                    was_summarized=was_summarized,
                )
                if self._channel is not None:
                    self._channel.emit_tool_completed(
                        tool_use_id, tool_name, False,
                        result_chars=len(result_text),
                        was_summarized=was_summarized,
                        was_truncated=was_truncated,
                        duration_ms=duration_ms,
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
                if self._channel is not None:
                    self._channel.emit_tool_completed(
                        tool_use_id, tool_name, True,
                        result_chars=len(content),
                        duration_ms=duration_ms,
                    )
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                    "is_error": True,
                }

        return list(await asyncio.gather(*(run_one(b) for b in tool_use_blocks)))

    @staticmethod
    def _merge_tool_results(
        original_blocks: list[dict],
        inline_results: list[dict],
        regular_results: list[dict],
    ) -> list[dict]:
        """Merge inline (pseudo) and regular tool results in original block order."""
        by_id: dict[str, dict] = {}
        for r in inline_results:
            by_id[r["tool_use_id"]] = r
        for r in regular_results:
            by_id[r["tool_use_id"]] = r
        return [by_id[b["id"]] for b in original_blocks if b["id"] in by_id]

    def _resolve_tool_result_overrides(self, tool_name: str) -> tuple[bool, int, int]:
        """Resolve effective (summarize_enabled, threshold, max_chars) for a tool.

        Per-tool ``ToolResultOverrides`` win over the global defaults; any field the
        override leaves as ``None`` falls through. Truncation always runs (with the
        resolved cap); summarization runs only when ``summarize_enabled`` is True
        and the result length exceeds ``threshold``.

        Override keys are matched exact-first; if no exact match is found, keys
        ending in ``*`` are tried as prefix matches (first match in insertion
        order wins). This lets a single entry cover all tools from one MCP
        server, e.g. ``"playwright__*"``.
        """
        summarize = self._summarization_enabled
        threshold = self._summarization_threshold
        max_chars = self._max_tool_result_chars
        override = self._tool_result_overrides.get(tool_name)
        if override is None:
            for key, candidate in self._tool_result_overrides.items():
                if key.endswith("*") and tool_name.startswith(key[:-1]):
                    override = candidate
                    break
        if override is not None:
            if override.summarize is not None:
                summarize = override.summarize
            if override.threshold is not None:
                threshold = override.threshold
            if override.max_chars is not None:
                max_chars = override.max_chars
        return summarize, threshold, max_chars

    async def _summarize_tool_result(
        self,
        result: str,
        tool_name: str,
        summarize_enabled: bool,
        threshold: int,
    ) -> tuple[str, bool]:
        """Summarize a large tool result using a cheaper model.

        Returns (possibly-summarized result, was_summarized).
        """
        if not summarize_enabled or self._summarization_provider is None or len(result) <= threshold:
            return result, False

        prompt = (
            "Summarize this tool output concisely, preserving all decision-relevant "
            "data (names, numbers, IDs, paths, errors) and all URLs verbatim. "
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
            logger.info(f"Summarized {tool_name} result: {len(result):,} chars -> {len(summary):,} chars")
            return summary, True
        except Exception as ex:
            logger.warning(f"Tool result summarization failed for {tool_name}: {ex}")
            return result, False

    def _track_nested_llm_usage(self, tool_name: str, structured: Any) -> None:
        """Track LLM usage reported by an MCP tool in its structured result.

        Usage may be reported either at the top level of the structured result
        or nested under a ``_usage`` key (codegen ``run_task`` surfaces the task
        subprocess's ``__USAGE__`` report this way). A nested ``_usage`` dict
        takes precedence when present.
        """
        if not isinstance(structured, dict):
            return
        nested = structured.get("_usage")
        usage_src = nested if isinstance(nested, dict) else structured
        input_tokens = usage_src.get("input_tokens")
        output_tokens = usage_src.get("output_tokens")
        model = usage_src.get("model")
        if input_tokens is None or output_tokens is None or model is None:
            return
        structured = usage_src
        usage = UsageResult(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_input_tokens=structured.get("cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=structured.get("cache_read_input_tokens", 0) or 0,
            provider=structured.get("provider", "anthropic"),
            model=model,
        )
        self._events.on_api_call_completed(usage, f"nested:{tool_name}")

    def _truncate_tool_result(self, result: str, tool_name: str, max_chars: int) -> tuple[str, bool]:
        if max_chars <= 0 or len(result) <= max_chars:
            return result, False

        original_length = len(result)
        truncated = result[:max_chars]
        message = f"\n\n[OUTPUT TRUNCATED: Showing {max_chars:,} of {original_length:,} characters from {tool_name}]"
        logger.warning(f"{tool_name} output truncated from {original_length:,} to {max_chars:,} chars")
        return truncated + message, True
