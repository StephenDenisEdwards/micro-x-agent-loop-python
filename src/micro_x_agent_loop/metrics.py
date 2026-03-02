from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from loguru import logger

from micro_x_agent_loop.usage import UsageResult, _lookup_pricing, estimate_cost

_metrics_logger = logger.bind(metrics=True)


def emit_metric(record: dict) -> None:
    """Write a structured JSON metric record to the metrics loguru sink."""
    _metrics_logger.info(json.dumps(record, default=str))


def build_api_call_metric(
    usage: UsageResult,
    session_id: str,
    turn_number: int,
    call_type: str,
) -> dict:
    return {
        "type": "api_call",
        "timestamp": time.time(),
        "session_id": session_id,
        "turn_number": turn_number,
        "call_type": call_type,
        "provider": usage.provider,
        "model": usage.model,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_creation_input_tokens": usage.cache_creation_input_tokens,
        "cache_read_input_tokens": usage.cache_read_input_tokens,
        "message_count": usage.message_count,
        "tool_schema_count": usage.tool_schema_count,
        "stop_reason": usage.stop_reason,
        "duration_ms": usage.duration_ms,
        "time_to_first_token_ms": usage.time_to_first_token_ms,
        "estimated_cost_usd": estimate_cost(usage),
    }


def build_tool_execution_metric(
    tool_name: str,
    result_chars: int,
    duration_ms: float,
    is_error: bool,
    session_id: str,
    turn_number: int,
    *,
    was_summarized: bool = False,
) -> dict:
    return {
        "type": "tool_execution",
        "timestamp": time.time(),
        "session_id": session_id,
        "turn_number": turn_number,
        "tool_name": tool_name,
        "result_chars": result_chars,
        "result_estimated_tokens": result_chars // 4,
        "duration_ms": duration_ms,
        "is_error": is_error,
        "was_summarized": was_summarized,
    }


def build_compaction_metric(
    usage: UsageResult,
    tokens_before: int,
    tokens_after: int,
    messages_compacted: int,
    session_id: str,
    turn_number: int,
) -> dict:
    return {
        "type": "compaction",
        "timestamp": time.time(),
        "session_id": session_id,
        "turn_number": turn_number,
        "compaction_model": usage.model,
        "compaction_input_tokens": usage.input_tokens,
        "compaction_output_tokens": usage.output_tokens,
        "compaction_cost_usd": estimate_cost(usage),
        "estimated_tokens_before": tokens_before,
        "estimated_tokens_after": tokens_after,
        "tokens_freed": tokens_before - tokens_after,
        "messages_compacted": messages_compacted,
    }


def build_session_summary_metric(accumulator: SessionAccumulator) -> dict:
    return {
        "type": "session_summary",
        "timestamp": time.time(),
        "session_id": accumulator.session_id,
        "total_turns": accumulator.total_turns,
        "total_input_tokens": accumulator.total_input_tokens,
        "total_output_tokens": accumulator.total_output_tokens,
        "total_cache_creation_tokens": accumulator.total_cache_creation_tokens,
        "total_cache_read_tokens": accumulator.total_cache_read_tokens,
        "total_cost_usd": accumulator.total_cost_usd,
        "total_api_calls": accumulator.total_api_calls,
        "total_tool_calls": accumulator.total_tool_calls,
        "total_tool_errors": accumulator.total_tool_errors,
        "total_compaction_events": accumulator.total_compaction_events,
        "tool_call_counts": dict(accumulator.tool_call_counts),
        "total_duration_ms": accumulator.total_duration_ms,
        "model_subtotals": dict(accumulator.model_subtotals),
    }


@dataclass
class SessionAccumulator:
    session_id: str = ""
    provider: str = ""
    model: str = ""
    total_turns: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_creation_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cost_usd: float = 0.0
    total_api_calls: int = 0
    total_tool_calls: int = 0
    total_tool_errors: int = 0
    total_compaction_events: int = 0
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    total_duration_ms: float = 0.0
    model_subtotals: dict[str, dict] = field(default_factory=dict)

    def reset(self, session_id: str = "") -> None:
        """Reset all counters for a new session."""
        self.session_id = session_id
        self.provider = ""
        self.model = ""
        self.total_turns = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_creation_tokens = 0
        self.total_cache_read_tokens = 0
        self.total_cost_usd = 0.0
        self.total_api_calls = 0
        self.total_tool_calls = 0
        self.total_tool_errors = 0
        self.total_compaction_events = 0
        self.tool_call_counts.clear()
        self.total_duration_ms = 0.0
        self.model_subtotals.clear()

    def _record_model(self, usage: UsageResult) -> None:
        cost = estimate_cost(usage)
        model = usage.model or "unknown"
        sub = self.model_subtotals.get(model)
        if sub is None:
            sub = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
            self.model_subtotals[model] = sub
        sub["calls"] += 1
        sub["input_tokens"] += usage.input_tokens
        sub["output_tokens"] += usage.output_tokens
        sub["cost_usd"] += cost

    def add_api_call(self, usage: UsageResult) -> None:
        self.total_api_calls += 1
        if not self.model and usage.model:
            self.provider = usage.provider
            self.model = usage.model
        self.total_input_tokens += usage.input_tokens
        self.total_output_tokens += usage.output_tokens
        self.total_cache_creation_tokens += usage.cache_creation_input_tokens
        self.total_cache_read_tokens += usage.cache_read_input_tokens
        self.total_cost_usd += estimate_cost(usage)
        self.total_duration_ms += usage.duration_ms
        self._record_model(usage)

    def add_tool_call(self, tool_name: str, is_error: bool) -> None:
        self.total_tool_calls += 1
        if is_error:
            self.total_tool_errors += 1
        self.tool_call_counts[tool_name] = self.tool_call_counts.get(tool_name, 0) + 1

    def add_compaction(self, usage: UsageResult) -> None:
        self.total_compaction_events += 1
        self.total_cost_usd += estimate_cost(usage)
        self._record_model(usage)

    def format_summary(self) -> str:
        lines = [
            "Session Cost Summary",
            "--------------------",
            f"Provider/Model:     {self.provider or '—'} / {self.model or '—'}",
        ]
        prices = _lookup_pricing(self.model) if self.model else None
        if prices:
            inp, out, cr, cw = prices
            lines.append(f"Pricing (per MTok):  in=${inp} out=${out} cache_read=${cr} cache_write=${cw}")
        elif self.model:
            lines.append("Pricing (per MTok):  (unknown model — cost estimated as $0)")
        lines += [
            f"Total API calls:    {self.total_api_calls}",
            f"Total turns:        {self.total_turns}",
            f"Input tokens:       {self.total_input_tokens:,}",
            f"Output tokens:      {self.total_output_tokens:,}",
            f"Cache read tokens:  {self.total_cache_read_tokens:,}",
            f"Cache create tokens:{self.total_cache_creation_tokens:,}",
            f"Total cost:         ${self.total_cost_usd:.6f}",
            f"Total duration:     {self.total_duration_ms:,.0f} ms",
            f"Tool calls:         {self.total_tool_calls} ({self.total_tool_errors} errors)",
            f"Compaction events:  {self.total_compaction_events}",
        ]
        if len(self.model_subtotals) > 1:
            lines.append("Model breakdown:")
            for model, sub in sorted(self.model_subtotals.items(), key=lambda x: -x[1]["cost_usd"]):
                prices = _lookup_pricing(model)
                pricing_str = (
                    f" (in=${prices[0]} out=${prices[1]})" if prices else ""
                )
                lines.append(
                    f"  {model}{pricing_str}: {sub['calls']} calls, "
                    f"{sub['input_tokens']:,} in / {sub['output_tokens']:,} out, "
                    f"${sub['cost_usd']:.6f}"
                )
        if self.tool_call_counts:
            lines.append("Tool breakdown:")
            for name, count in sorted(self.tool_call_counts.items(), key=lambda x: -x[1]):
                lines.append(f"  {name}: {count}")
        return "\n".join(lines)
