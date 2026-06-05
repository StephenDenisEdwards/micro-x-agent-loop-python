"""AgentEventListener — pure-observability subset of the TurnEvents protocol.

Owns the methods that don't mutate ``Agent._messages`` or checkpoint state:
metric emission, API-call lifecycle, tool-execution telemetry, sub-agent
completion, compaction completion, and the verbatim LLM-call capture.
Message-history and checkpoint TurnEvents callbacks stay on ``Agent``
itself because they need to mutate that state.

Dependencies are injected so the listener can be unit-tested without a
full ``Agent``.
"""

from __future__ import annotations

from collections.abc import Callable

from loguru import logger

from micro_x_agent_loop.memory.facade import ActiveMemoryFacade, NullMemoryFacade
from micro_x_agent_loop.metrics import (
    SessionAccumulator,
    build_api_call_error_metric,
    build_api_call_metric,
    build_compaction_metric,
    build_tool_execution_metric,
)
from micro_x_agent_loop.observability import ObservabilityEmitter
from micro_x_agent_loop.usage import UsageResult


class AgentEventListener:
    """Implements the metric/event subset of TurnEvents."""

    def __init__(
        self,
        *,
        memory: ActiveMemoryFacade | NullMemoryFacade,
        obs: ObservabilityEmitter,
        session_accumulator: SessionAccumulator,
        metrics_enabled: bool,
        turn_number_provider: Callable[[], int],
        compaction_tokens_handler: Callable[[int], None] | None = None,
        budget_check: Callable[[], None] | None = None,
    ) -> None:
        self._memory = memory
        self._obs = obs
        self._acc = session_accumulator
        self._metrics_enabled = metrics_enabled
        self._turn_number = turn_number_provider
        self._compaction_tokens_handler = compaction_tokens_handler
        self._budget_check = budget_check

    # -- API call lifecycle -------------------------------------------------

    def on_api_call_completed(self, usage: UsageResult, call_type: str) -> None:
        # Feed actual token count to smart compaction trigger
        if call_type == "main" and self._compaction_tokens_handler is not None:
            self._compaction_tokens_handler(usage.input_tokens)

        if not self._metrics_enabled:
            return
        tn = self._turn_number()
        self._acc.add_api_call(usage, call_type=call_type, turn_number=tn)

        # Budget warning at threshold (once per session)
        if self._budget_check is not None:
            self._budget_check()
        metric = build_api_call_metric(
            usage,
            session_id=self._memory.active_session_id or "",
            turn_number=tn,
            call_type=call_type,
        )
        self._obs.emit("metric.api_call", metric, turn_number=tn)

    def on_api_call_failed(
        self, *, model: str, provider: str, call_type: str, error: BaseException
    ) -> None:
        # A terminal LLM call failure (provider retry already exhausted). The
        # success metric never fires on error, so record it here — otherwise a
        # 429 / timeout leaves no structured trace. Always log a warning for
        # visibility in agent.log; emit the structured metric when enabled.
        logger.warning(
            "API call failed: provider={provider} model={model} call_type={call_type} error={err}",
            provider=provider or "?",
            model=model or "?",
            call_type=call_type,
            err=f"{type(error).__name__}: {error}"[:300],
        )
        if not self._metrics_enabled:
            return
        tn = self._turn_number()
        metric = build_api_call_error_metric(
            model=model,
            provider=provider,
            session_id=self._memory.active_session_id or "",
            turn_number=tn,
            call_type=call_type,
            error=error,
        )
        self._obs.emit("metric.api_call_error", metric, turn_number=tn)

    def on_turn_cap_reached(self, iterations: int) -> None:
        # Behavioural signal (set regardless of metrics_enabled): the turn
        # stopped because it hit MaxAgenticIterations, not because the model
        # finished. Surfaced via SessionAccumulator so evals can assert on it.
        self._acc.turn_cap_reached = True
        logger.warning(
            "Agentic turn cap reached: {n} iterations (MaxAgenticIterations)",
            n=iterations,
        )

    # -- Tool / sub-agent telemetry -----------------------------------------

    def on_tool_executed(
        self,
        tool_name: str,
        result_chars: int,
        duration_ms: float,
        is_error: bool,
        *,
        was_summarized: bool = False,
    ) -> None:
        if not self._metrics_enabled:
            return
        tn = self._turn_number()
        self._acc.add_tool_call(tool_name, is_error)
        metric = build_tool_execution_metric(
            tool_name=tool_name,
            result_chars=result_chars,
            duration_ms=duration_ms,
            is_error=is_error,
            session_id=self._memory.active_session_id or "",
            turn_number=tn,
            was_summarized=was_summarized,
        )
        self._obs.emit("metric.tool_execution", metric, turn_number=tn)

    def on_subagent_completed(
        self,
        *,
        agent_type: str,
        task: str,
        result_summary: str,
        turns: int,
        timed_out: bool,
        cost_usd: float,
        api_calls: int,
    ) -> None:
        self._memory.emit_event(
            "subagent.completed",
            {
                "agent_type": agent_type,
                "task": task[:500],
                "result_summary": result_summary[:500],
                "turns": turns,
                "timed_out": timed_out,
                "cost_usd": cost_usd,
                "api_calls": api_calls,
            },
        )

    def on_record_tool_call(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        tool_input: dict,
        result_text: str,
        is_error: bool,
        message_id: str | None,
        was_truncated: bool = False,
        original_chars: int | None = None,
    ) -> None:
        self._memory.record_tool_call(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_input=tool_input,
            result_text=result_text,
            is_error=is_error,
            message_id=message_id,
            was_truncated=was_truncated,
            original_chars=original_chars,
        )

    # -- Compaction metric --------------------------------------------------

    def on_compaction_completed(
        self, usage: UsageResult, tokens_before: int, tokens_after: int, messages_compacted: int
    ) -> None:
        tn = self._turn_number()
        self._acc.add_compaction(usage)
        metric = build_compaction_metric(
            usage=usage,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            messages_compacted=messages_compacted,
            session_id=self._memory.active_session_id or "",
            turn_number=tn,
        )
        self._obs.emit("metric.compaction", metric, turn_number=tn)

    # -- Verbatim LLM-call capture ------------------------------------------

    def on_llm_call(
        self,
        *,
        turn_iteration: int,
        call_type: str,
        effective_provider: str,
        effective_model: str,
        temperature: float,
        max_tokens: int,
        message_count: int,
        tool_names: list[str],
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        routing_rule: str = "",
        routing_reason: str = "",
    ) -> None:
        # Step-through trace of the exact LLM input. The full prompt is deduped
        # into the system_prompts table; the event carries only its hash + size.
        sha = self._memory.persist_system_prompt(system_prompt)
        # Verbatim capture (opt-in): persist the exact system prompt + messages +
        # tool schemas so /replay --full can show byte-for-byte what was sent.
        tn = self._turn_number()
        request_id = self._memory.persist_llm_request(
            turn_number=tn,
            iteration=turn_iteration,
            system_prompt_sha256=sha or "",
            messages=messages,
            tools=tools,
        )
        self._obs.emit(
            "llm.call",
            {
                "session_id": self._memory.active_session_id or "",
                "turn_number": tn,
                "call_type": call_type,
                "effective_provider": effective_provider,
                "effective_model": effective_model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "message_count": message_count,
                "tool_names": tool_names,
                "system_prompt_sha256": sha,
                "system_prompt_chars": len(system_prompt),
                "request_id": request_id,
                "routing_rule": routing_rule,
                "routing_reason": routing_reason,
            },
            turn_number=tn,
            iteration=turn_iteration,
        )
