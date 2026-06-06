from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from loguru import logger

from micro_x_agent_loop.agent_channel import ASK_USER_SCHEMA
from micro_x_agent_loop.api_payload_store import ApiPayload, ApiPayloadStore
from micro_x_agent_loop.constants import DEFAULT_MAX_AGENTIC_ITERATIONS
from micro_x_agent_loop.embedding import TaskEmbeddingIndex
from micro_x_agent_loop.provider import LLMCompactor, LLMProvider
from micro_x_agent_loop.provider_pool import ProviderPool, RoutingTarget
from micro_x_agent_loop.pseudo_tool_handlers import (
    AskUserHandler,
    PseudoToolHandler,
    PseudoToolRegistry,
    SubAgentHandler,
    TaskToolHandler,
    ToolSearchHandler,
)
from micro_x_agent_loop.routing_strategy import RoutingDecision, RoutingStrategy
from micro_x_agent_loop.semantic_classifier import TaskClassification
from micro_x_agent_loop.sub_agent import SPAWN_SUBAGENT_SCHEMA, SubAgentRunner
from micro_x_agent_loop.system_prompt import resolve_system_prompt
from micro_x_agent_loop.tasks.manager import TaskManager
from micro_x_agent_loop.tasks.schemas import ALL_TASK_SCHEMAS
from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.tool_dispatcher import ToolDispatcher
from micro_x_agent_loop.tool_result_formatter import ToolResultFormatter
from micro_x_agent_loop.tool_search import ToolSearchManager
from micro_x_agent_loop.turn_events import TurnEvents
from micro_x_agent_loop.usage import estimate_cost

if TYPE_CHECKING:
    from micro_x_agent_loop.agent_channel import AgentChannel
    from micro_x_agent_loop.app_config import ToolResultOverride

# Callable signatures for routing collaborators (used as legacy params).
SemanticClassifierFn = Callable[..., TaskClassification]
RoutingFeedbackFn = Callable[..., None]


class TurnEngine:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        model: str,
        max_tokens: int,
        temperature: float,
        system_prompt: str,
        converted_tools: list[dict],
        tool_map: dict[str, Tool],
        max_tool_result_chars: int,
        max_tokens_retries: int,
        max_agentic_iterations: int = DEFAULT_MAX_AGENTIC_ITERATIONS,
        events: TurnEvents,
        channel: AgentChannel | None = None,
        summarization_provider: LLMCompactor | None = None,
        summarization_model: str = "",
        summarization_enabled: bool = False,
        summarization_threshold: int = 4000,
        formatter: ToolResultFormatter | None = None,
        api_payload_store: ApiPayloadStore | None = None,
        tool_search_manager: ToolSearchManager | None = None,
        tool_search_globally_active: bool = False,
        compact_system_prompt: str = "",
        sub_agent_runner: SubAgentRunner | None = None,
        task_manager: TaskManager | None = None,
        routing: RoutingStrategy | None = None,
        # Legacy params — used when `routing` is None (backward compat for tests)
        provider_pool: ProviderPool | None = None,
        semantic_classifier: SemanticClassifierFn | None = None,
        routing_policies: dict[str, dict] | None = None,
        routing_fallback_provider: str = "",
        routing_fallback_model: str = "",
        routing_feedback_callback: RoutingFeedbackFn | None = None,
        routing_confidence_threshold: float = 0.6,
        task_embedding_index: TaskEmbeddingIndex | None = None,
        tool_result_overrides: dict[str, ToolResultOverride] | None = None,
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
        self._max_agentic_iterations = max_agentic_iterations
        self._events = events
        self._channel = channel
        self._summarization_provider = summarization_provider
        self._summarization_model = summarization_model
        self._summarization_enabled = summarization_enabled
        self._summarization_threshold = summarization_threshold
        self._tool_result_overrides = tool_result_overrides or {}
        self._formatter = formatter or ToolResultFormatter()
        self._api_payload_store = api_payload_store
        self._tool_search_manager = tool_search_manager
        self._tool_search_globally_active = tool_search_globally_active
        self._compact_system_prompt = compact_system_prompt
        self._sub_agent_runner = sub_agent_runner
        self._task_manager = task_manager
        # Pseudo-tool dispatch — each handler declares the exact tool names
        # it claims; PseudoToolRegistry builds a name→handler dict and
        # raises ValueError if two handlers claim the same name. No more
        # first-match-wins ambiguity. Adding a new pseudo tool means
        # writing a handler with a unique claimed_names() set.
        pseudo_handlers: list[PseudoToolHandler] = []
        if tool_search_manager is not None:
            pseudo_handlers.append(ToolSearchHandler(tool_search_manager))
        if channel is not None:
            pseudo_handlers.append(AskUserHandler(channel))
        if task_manager is not None:
            pseudo_handlers.append(TaskToolHandler(task_manager))
        if sub_agent_runner is not None:
            pseudo_handlers.append(
                SubAgentHandler(sub_agent_runner, channel=channel, events=events),
            )
        self._pseudo_registry = PseudoToolRegistry(pseudo_handlers)
        self._dispatcher = ToolDispatcher(
            pseudo_registry=self._pseudo_registry,
            tool_map=self._tool_map,
            events=self._events,
            channel=self._channel,
            formatter=self._formatter,
            max_tool_result_chars=self._max_tool_result_chars,
            summarization_provider=self._summarization_provider,
            summarization_model=self._summarization_model,
            summarization_enabled=self._summarization_enabled,
            summarization_threshold=self._summarization_threshold,
            tool_result_overrides=self._tool_result_overrides,
        )
        # Build RoutingStrategy from legacy params if not provided directly
        resolved_routing: RoutingStrategy | None = None
        if routing is not None:
            resolved_routing = routing
        elif semantic_classifier is not None:
            resolved_routing = RoutingStrategy(
                default_model=model,
                provider_pool=provider_pool,
                semantic_classifier=semantic_classifier,
                routing_policies=routing_policies,
                routing_fallback_provider=routing_fallback_provider,
                routing_fallback_model=routing_fallback_model,
                routing_confidence_threshold=routing_confidence_threshold,
                routing_feedback_callback=routing_feedback_callback,
                compact_system_prompt=compact_system_prompt,
                task_embedding_index=task_embedding_index,
                tool_search_manager=tool_search_manager,
            )
        self._routing = resolved_routing
        # Keep direct references needed outside of routing
        self._routing_fallback_provider = (
            routing_fallback_provider if routing is None else (routing.fallback_provider if routing else "")
        )
        self._routing_fallback_model = (
            routing_fallback_model if routing is None else (routing.fallback_model if routing else "")
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
            if turn_iteration >= self._max_agentic_iterations:
                # Hard safety rail: the loop is otherwise unbounded (exits only
                # when the model stops requesting tools). Stop cleanly — mirror
                # the max_tokens give-up path; no exception.
                if self._channel is not None:
                    self._channel.emit_error(
                        f"Stopped: agentic turn cap reached "
                        f"({self._max_agentic_iterations} iterations) without "
                        f"converging. Raise MaxAgenticIterations if the task "
                        f"legitimately needs more tool steps."
                    )
                self._events.on_turn_cap_reached(turn_iteration)
                return current_user_message_id, last_assistant_message_id

            system_prompt = resolve_system_prompt(self._system_prompt_template)

            # When tool search is globally active, send only the search tool + loaded tools
            api_tools = (
                self._tool_search_manager.get_tools_for_api_call()
                if self._tool_search_globally_active and self._tool_search_manager is not None
                else list(self._converted_tools)
            )
            if self._sub_agent_runner is not None:
                api_tools.append(SPAWN_SUBAGENT_SCHEMA)
            if self._task_manager is not None:
                api_tools.extend(ALL_TASK_SCHEMAS)
            if self._channel is not None:
                api_tools.append(ASK_USER_SCHEMA)

            # Model routing via RoutingStrategy
            effective_model = self._model
            effective_provider: Any = None
            task_classification = None
            call_type = "main"
            routing_target: RoutingTarget | None = None
            decision: RoutingDecision | None = None

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

            # Resolve the effective provider name once, up front, so it can be
            # reported on the llm.call event and reused as the dispatch target.
            if effective_provider is not None and isinstance(effective_provider, ProviderPool):
                dispatch_provider = (
                    routing_target.provider if routing_target is not None else self._routing_fallback_provider
                )
            else:
                dispatch_provider = getattr(self._provider, "family", "")

            # Step-through trace: exactly what is about to go to the model.
            self._events.on_llm_call(
                turn_iteration=turn_iteration,
                call_type=call_type,
                effective_provider=dispatch_provider,
                effective_model=effective_model,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                message_count=len(messages),
                tool_names=[str(t.get("name", "")) for t in api_tools],
                system_prompt=system_prompt,
                messages=messages,
                tools=api_tools,
                routing_rule=call_type,
                routing_reason=decision.reason if decision is not None else "",
            )

            # Dispatch to provider. The provider's own tenacity retry is
            # exhausted by the time an exception reaches us, so a raise here is
            # terminal for the call — record it as a metric before re-raising.
            # The success path below never runs on error, which previously left
            # 429s / timeouts with no structured trace (success-only ledger).
            try:
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
            except Exception as exc:
                self._events.on_api_call_failed(
                    model=effective_model,
                    provider=dispatch_provider,
                    call_type=call_type,
                    error=exc,
                )
                raise

            self._events.on_api_call_completed(usage, call_type)

            # Routing feedback callback
            if self._routing is not None and self._routing.feedback_callback and task_classification is not None:
                self._routing.feedback_callback(
                    task_classification=task_classification,
                    usage=usage,
                    call_type=call_type,
                    decision=decision,
                )

            if self._api_payload_store is not None:
                self._record_api_payload(
                    system_prompt,
                    messages,
                    message,
                    stop_reason,
                    usage,
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

            dispatch = await self._dispatcher.dispatch(
                tool_use_blocks, last_assistant_message_id=last_assistant_message_id
            )
            self._events.on_append_message("user", dispatch.results)
            # Only compact when regular tools ran — pseudo-only turns are
            # cheap and the previous behaviour was to skip compaction here.
            if dispatch.ran_regular_tools:
                await self._events.on_maybe_compact()
            turn_iteration += 1

    async def execute_tools(
        self,
        tool_use_blocks: list[dict],
        *,
        last_assistant_message_id: str | None,
    ) -> list[dict]:
        """Thin proxy to ToolDispatcher for back-compat with external callers
        (``Agent._execute_tools``, integration tests). The dispatcher is the
        single source of truth for regular MCP tool execution.
        """
        return await self._dispatcher.execute_tools(
            tool_use_blocks, last_assistant_message_id=last_assistant_message_id
        )

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
