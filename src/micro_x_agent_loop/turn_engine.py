from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from micro_x_agent_loop.agent_channel import ASK_USER_SCHEMA
from micro_x_agent_loop.api_payload_store import ApiPayload, ApiPayloadStore
from micro_x_agent_loop.provider_pool import ProviderPool, RoutingTarget
from micro_x_agent_loop.routing_strategy import RoutingStrategy
from micro_x_agent_loop.sub_agent import SPAWN_SUBAGENT_SCHEMA, SubAgentRunner, SubAgentType
from micro_x_agent_loop.usage import UsageResult, estimate_cost

if TYPE_CHECKING:
    from micro_x_agent_loop.agent_channel import AgentChannel
from micro_x_agent_loop.system_prompt import resolve_system_prompt
from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.tool_result_formatter import ToolResultFormatter
from micro_x_agent_loop.tool_search import ToolSearchManager
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
        max_tool_result_chars: int,
        max_tokens_retries: int,
        events: TurnEvents,
        channel: AgentChannel | None = None,
        summarization_provider: Any | None = None,
        summarization_model: str = "",
        summarization_enabled: bool = False,
        summarization_threshold: int = 4000,
        formatter: ToolResultFormatter | None = None,
        api_payload_store: ApiPayloadStore | None = None,
        tool_search_manager: ToolSearchManager | None = None,
        tool_search_globally_active: bool = False,
        compact_system_prompt: str = "",
        sub_agent_runner: SubAgentRunner | None = None,
        routing: RoutingStrategy | None = None,
        # Legacy params — used when `routing` is None (backward compat for tests)
        turn_classifier: Any | None = None,
        routing_model: str = "",
        provider_pool: ProviderPool | None = None,
        semantic_classifier: Any | None = None,
        routing_policies: dict[str, dict] | None = None,
        routing_fallback_provider: str = "",
        routing_fallback_model: str = "",
        routing_feedback_callback: Any | None = None,
        routing_confidence_threshold: float = 0.6,
        task_embedding_index: Any | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._system_prompt_template = system_prompt
        self._converted_tools = converted_tools
        self._tool_map = tool_map
        self._max_tool_result_chars = max_tool_result_chars
        self._max_tokens_retries = max_tokens_retries
        self._events = events
        self._channel = channel
        self._summarization_provider = summarization_provider
        self._summarization_model = summarization_model
        self._summarization_enabled = summarization_enabled
        self._summarization_threshold = summarization_threshold
        self._formatter = formatter or ToolResultFormatter()
        self._api_payload_store = api_payload_store
        self._tool_search_manager = tool_search_manager
        self._tool_search_globally_active = tool_search_globally_active
        self._compact_system_prompt = compact_system_prompt
        self._sub_agent_runner = sub_agent_runner
        # Build RoutingStrategy from legacy params if not provided directly
        resolved_routing: RoutingStrategy | None = None
        if routing is not None:
            resolved_routing = routing
        elif semantic_classifier is not None or turn_classifier is not None:
            resolved_routing = RoutingStrategy(
                default_model=model,
                provider_pool=provider_pool,
                semantic_classifier=semantic_classifier,
                turn_classifier=turn_classifier,
                routing_policies=routing_policies,
                routing_fallback_provider=routing_fallback_provider,
                routing_fallback_model=routing_fallback_model,
                routing_confidence_threshold=routing_confidence_threshold,
                routing_model=routing_model,
                routing_feedback_callback=routing_feedback_callback,
                compact_system_prompt=compact_system_prompt,
                task_embedding_index=task_embedding_index,
                tool_search_manager=tool_search_manager,
            )
        self._routing = resolved_routing
        # Keep direct references needed outside of routing
        self._routing_fallback_provider = (
            routing_fallback_provider if routing is None
            else (routing.fallback_provider if routing else "")
        )
        self._routing_fallback_model = (
            routing_fallback_model if routing is None
            else (routing.fallback_model if routing else "")
        )

    async def run(
        self,
        *,
        messages: list[dict],
        user_message: str,
        turn_number: int = 0,
    ) -> tuple[str | None, str | None]:
        last_assistant_message_id: str | None = None
        current_user_message_id = self._events.on_append_message("user", user_message)
        self._events.on_user_message_appended(current_user_message_id)
        await self._events.on_maybe_compact()

        if self._tool_search_manager is not None:
            self._tool_search_manager.begin_turn()

        max_tokens_attempts = 0
        turn_iteration = 0
        pinned_target: RoutingTarget | None = None  # Set on iteration 0 if pin_continuation

        while True:
            system_prompt = resolve_system_prompt(self._system_prompt_template)

            # When tool search is globally active, send only the search tool + loaded tools
            api_tools = (
                self._tool_search_manager.get_tools_for_api_call()
                if self._tool_search_globally_active and self._tool_search_manager is not None
                else list(self._converted_tools)
            )
            if self._sub_agent_runner is not None:
                api_tools.append(SPAWN_SUBAGENT_SCHEMA)
            if self._channel is not None:
                api_tools.append(ASK_USER_SCHEMA)

            # Model routing via RoutingStrategy
            effective_model = self._model
            effective_provider: Any = None
            task_classification = None
            call_type = "main"
            routing_target: RoutingTarget | None = None

            if self._routing is not None:
                decision = await self._routing.decide(
                    user_message=user_message,
                    turn_iteration=turn_iteration,
                    turn_number=turn_number,
                    api_tools=api_tools,
                    pinned_target=pinned_target,
                    channel=self._channel,
                )
                effective_model = decision.effective_model
                effective_provider = decision.effective_provider
                routing_target = decision.routing_target
                task_classification = decision.task_classification
                call_type = decision.call_type
                if decision.new_pinned_target is not None:
                    pinned_target = decision.new_pinned_target
                if decision.narrowed_tools is not None:
                    api_tools = decision.narrowed_tools
                if decision.system_prompt_override is not None:
                    system_prompt = decision.system_prompt_override

            # Dispatch to provider
            if effective_provider is not None and isinstance(effective_provider, ProviderPool):
                dispatch_target = routing_target or RoutingTarget(
                    provider=self._routing_fallback_provider,
                    model=effective_model,
                )
                message, tool_use_blocks, stop_reason, usage = await effective_provider.stream_chat(
                    dispatch_target,
                    self._max_tokens,
                    self._temperature,
                    system_prompt,
                    messages,
                    api_tools,
                    channel=self._channel,
                )
            else:
                message, tool_use_blocks, stop_reason, usage = await self._provider.stream_chat(
                    effective_model,
                    self._max_tokens,
                    self._temperature,
                    system_prompt,
                    messages,
                    api_tools,
                    channel=self._channel,
                )

            self._events.on_api_call_completed(usage, call_type)

            # Routing feedback callback
            if self._routing is not None and self._routing.feedback_callback and task_classification is not None:
                self._routing.feedback_callback(
                    task_classification=task_classification,
                    usage=usage,
                    call_type=call_type,
                )

            if self._api_payload_store is not None:
                self._record_api_payload(
                    system_prompt, messages, message, stop_reason, usage,
                    tools_count=len(api_tools),
                    effective_model=effective_model,
                )

            last_assistant_message_id = self._events.on_append_message("assistant", message["content"])

            if stop_reason == "max_tokens" and not tool_use_blocks:
                max_tokens_attempts += 1
                if max_tokens_attempts >= self._max_tokens_retries:
                    if self._channel is not None:
                        self._channel.emit_error(
                            f"Stopped: response exceeded max_tokens "
                            f"({self._max_tokens}) {self._max_tokens_retries} times in a row. "
                            f"Try increasing MaxTokens in config.json or simplifying the request."
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
                turn_iteration += 1
                continue

            max_tokens_attempts = 0

            if not tool_use_blocks:
                return current_user_message_id, last_assistant_message_id

            # Classify blocks: search / ask_user / subagent / regular
            search_blocks: list[dict] = []
            ask_user_blocks: list[dict] = []
            subagent_blocks: list[dict] = []
            regular_blocks: list[dict] = []
            for block in tool_use_blocks:
                name = block["name"]
                if self._tool_search_manager is not None and ToolSearchManager.is_tool_search_call(name):
                    search_blocks.append(block)
                elif self._channel is not None and name == "ask_user":
                    ask_user_blocks.append(block)
                elif self._sub_agent_runner is not None and name == "spawn_subagent":
                    subagent_blocks.append(block)
                else:
                    regular_blocks.append(block)

            # Handle tool_search calls inline (no MCP execution needed)
            inline_results: list[dict] = []
            for block in search_blocks:
                assert self._tool_search_manager is not None
                query = block["input"].get("query", "")
                result_text = await self._tool_search_manager.handle_tool_search(query)
                inline_results.append({
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": result_text,
                })
                logger.info(f"tool_search query={query!r} loaded={self._tool_search_manager.loaded_tool_count}")

            # Handle ask_user calls inline (route through the channel)
            for block in ask_user_blocks:
                assert self._channel is not None
                question = block["input"].get("question", "")
                options = block["input"].get("options")
                answer = await self._channel.ask_user(question, options)
                result_text = json.dumps({"answer": answer})
                inline_results.append({
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": result_text,
                })
                logger.info(f"ask_user question={question!r}")

            # Handle spawn_subagent calls (run sub-agents concurrently)
            if subagent_blocks:
                subagent_results = await self._execute_subagent_blocks(subagent_blocks)
                inline_results.extend(subagent_results)

            # If only pseudo-tool calls (no regular tools), append results and continue
            if not regular_blocks:
                self._events.on_append_message("user", inline_results)
                turn_iteration += 1
                continue

            # Execute regular tool calls
            if self._channel is not None:
                for b in regular_blocks:
                    self._channel.emit_tool_started(b["id"], b["name"])
            try:
                self._events.on_ensure_checkpoint_for_turn(regular_blocks)
                regular_results = await self.execute_tools(
                    regular_blocks, last_assistant_message_id=last_assistant_message_id
                )
            finally:
                if self._channel is not None:
                    for b in regular_blocks:
                        self._channel.emit_tool_completed(b["id"], b["name"], False)

            # Combine results in original order
            if inline_results:
                all_results = self._merge_tool_results(
                    tool_use_blocks, inline_results, regular_results,
                )
            else:
                all_results = regular_results

            self._events.on_append_message("user", all_results)
            await self._events.on_maybe_compact()
            turn_iteration += 1

    @staticmethod
    def _merge_tool_results(
        original_blocks: list[dict],
        inline_results: list[dict],
        regular_results: list[dict],
    ) -> list[dict]:
        """Merge inline (search/ask_user) and regular tool results in original block order."""
        by_id: dict[str, dict] = {}
        for r in inline_results:
            by_id[r["tool_use_id"]] = r
        for r in regular_results:
            by_id[r["tool_use_id"]] = r
        return [by_id[b["id"]] for b in original_blocks if b["id"] in by_id]

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

    async def _execute_subagent_blocks(self, blocks: list[dict]) -> list[dict]:
        """Execute one or more spawn_subagent calls concurrently."""

        async def _run_one(block: dict) -> dict:
            tool_input = block["input"]
            task = tool_input.get("task", "")
            type_str = tool_input.get("type", "explore")
            try:
                agent_type = SubAgentType(type_str)
            except ValueError:
                agent_type = SubAgentType.EXPLORE

            if self._channel is not None:
                self._channel.emit_tool_started(block["id"], f"subagent:{agent_type.value}")

            try:
                assert self._sub_agent_runner is not None
                result = await self._sub_agent_runner.run(task, agent_type)

                # Aggregate sub-agent usage to parent metrics
                for usage in result.usage:
                    self._events.on_api_call_completed(usage, f"subagent:{agent_type.value}")

                self._events.on_subagent_completed(
                    agent_type=agent_type.value,
                    task=task,
                    result_summary=result.text[:500],
                    turns=result.turns,
                    timed_out=result.timed_out,
                    cost_usd=sum(estimate_cost(u) for u in result.usage),
                    api_calls=len(result.usage),
                )

                logger.info(
                    f"spawn_subagent type={agent_type.value} turns={result.turns} "
                    f"result_chars={len(result.text)} timed_out={result.timed_out}"
                )

                return {
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": result.text,
                }
            except Exception as ex:
                logger.error(f"spawn_subagent failed: {ex}")
                return {
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": f"Sub-agent error: {ex}",
                    "is_error": True,
                }
            finally:
                if self._channel is not None:
                    self._channel.emit_tool_completed(block["id"], f"subagent:{agent_type.value}", False)

        return list(await asyncio.gather(*(_run_one(b) for b in blocks)))

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
            cache_creation_input_tokens=structured.get("cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=structured.get("cache_read_input_tokens", 0) or 0,
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
        *,
        tools_count: int | None = None,
        effective_model: str | None = None,
    ) -> None:
        payload = ApiPayload(
            timestamp=time.time(),
            model=effective_model or self._model,
            system_prompt=system_prompt,
            messages=list(messages),
            tools_count=tools_count if tools_count is not None else len(self._converted_tools),
            response_message=response_message,
            stop_reason=stop_reason,
            usage=usage,
        )
        assert self._api_payload_store is not None
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
