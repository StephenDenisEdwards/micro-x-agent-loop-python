from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from loguru import logger

from micro_x_agent_loop.constants import CHARS_TO_TOKENS_DIVISOR
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
    *,
    routing_rule: str = "",
    routing_reason: str = "",
) -> dict:
    metric: dict = {
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
    if routing_rule:
        metric["routing_rule"] = routing_rule
        metric["routing_reason"] = routing_reason
    return metric


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
        "result_estimated_tokens": result_chars // CHARS_TO_TOKENS_DIVISOR,
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
    api_call_log: list[dict] = field(default_factory=list)
    context_tokens: int = 0
    context_messages: int = 0

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
        self.api_call_log.clear()
        self.context_tokens = 0
        self.context_messages = 0

    def _record_model(self, usage: UsageResult) -> None:
        cost = estimate_cost(usage)
        provider = usage.provider or "unknown"
        model = usage.model or "unknown"
        key = f"{provider}/{model}"
        sub = self.model_subtotals.get(key)
        if sub is None:
            sub = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
                   "provider": provider, "model": model}
            self.model_subtotals[key] = sub
        sub["calls"] += 1
        sub["input_tokens"] += usage.input_tokens
        sub["output_tokens"] += usage.output_tokens
        sub["cost_usd"] += cost

    def add_api_call(self, usage: UsageResult, *, call_type: str = "", turn_number: int = 0) -> None:
        self.total_api_calls += 1
        if not self.model and usage.model:
            self.provider = usage.provider
            self.model = usage.model
        self.total_input_tokens += usage.input_tokens
        self.total_output_tokens += usage.output_tokens
        self.total_cache_creation_tokens += usage.cache_creation_input_tokens
        self.total_cache_read_tokens += usage.cache_read_input_tokens
        cost = estimate_cost(usage)
        self.total_cost_usd += cost
        self.total_duration_ms += usage.duration_ms
        self._record_model(usage)
        self.api_call_log.append({
            "call_number": self.total_api_calls,
            "turn": turn_number,
            "call_type": call_type,
            "provider": usage.provider or "unknown",
            "model": usage.model or "unknown",
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read": usage.cache_read_input_tokens,
            "cache_create": usage.cache_creation_input_tokens,
            "cost_usd": cost,
            "duration_ms": usage.duration_ms,
        })

    def restore_from_events(self, events: list[dict]) -> None:
        """Replay persisted metric events to restore session cost state.

        Each event dict has ``type`` and ``payload_json`` (parsed) fields
        from the events table.
        """
        max_turn = 0
        for evt in events:
            etype = evt.get("type", "")
            payload = evt.get("payload", {})

            if etype == "metric.api_call":
                self.total_api_calls += 1
                self.total_input_tokens += int(payload.get("input_tokens", 0))
                self.total_output_tokens += int(payload.get("output_tokens", 0))
                self.total_cache_creation_tokens += int(payload.get("cache_creation_input_tokens", 0))
                self.total_cache_read_tokens += int(payload.get("cache_read_input_tokens", 0))
                self.total_cost_usd += float(payload.get("estimated_cost_usd", 0))
                self.total_duration_ms += float(payload.get("duration_ms", 0))
                turn = int(payload.get("turn_number", 0))
                if turn > max_turn:
                    max_turn = turn
                provider = payload.get("provider", "unknown")
                model = payload.get("model", "unknown")
                if not self.model and model:
                    self.provider = provider
                    self.model = model
                key = f"{provider}/{model}"
                sub = self.model_subtotals.get(key)
                if sub is None:
                    sub = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
                           "provider": provider, "model": model}
                    self.model_subtotals[key] = sub
                sub["calls"] += 1
                sub["input_tokens"] += int(payload.get("input_tokens", 0))
                sub["output_tokens"] += int(payload.get("output_tokens", 0))
                sub["cost_usd"] += float(payload.get("estimated_cost_usd", 0))
                self.api_call_log.append({
                    "call_number": self.total_api_calls,
                    "turn": turn,
                    "call_type": payload.get("call_type", ""),
                    "provider": provider,
                    "model": model,
                    "input_tokens": int(payload.get("input_tokens", 0)),
                    "output_tokens": int(payload.get("output_tokens", 0)),
                    "cache_read": int(payload.get("cache_read_input_tokens", 0)),
                    "cache_create": int(payload.get("cache_creation_input_tokens", 0)),
                    "cost_usd": float(payload.get("estimated_cost_usd", 0)),
                    "duration_ms": float(payload.get("duration_ms", 0)),
                })

            elif etype == "metric.compaction":
                self.total_compaction_events += 1
                self.total_cost_usd += float(payload.get("compaction_cost_usd", 0))

            elif etype == "metric.tool_execution":
                self.total_tool_calls += 1
                if payload.get("is_error"):
                    self.total_tool_errors += 1
                tool_name = payload.get("tool_name", "unknown")
                self.tool_call_counts[tool_name] = self.tool_call_counts.get(tool_name, 0) + 1

        self.total_turns = max_turn

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
        prices = _lookup_pricing(self.provider, self.model) if self.model else None
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
            for key, sub in sorted(self.model_subtotals.items(), key=lambda x: -x[1]["cost_usd"]):
                prices = _lookup_pricing(sub.get("provider", ""), sub.get("model", ""))
                pricing_str = (
                    f" (in=${prices[0]} out=${prices[1]})" if prices else ""
                )
                lines.append(
                    f"  {key}{pricing_str}: {sub['calls']} calls, "
                    f"{sub['input_tokens']:,} in / {sub['output_tokens']:,} out, "
                    f"${sub['cost_usd']:.6f}"
                )
        if self.tool_call_counts:
            lines.append("Tool breakdown:")
            for name, count in sorted(self.tool_call_counts.items(), key=lambda x: -x[1]):
                lines.append(f"  {name}: {count}")
        if self.api_call_log:
            lines.append("Per-call breakdown:")
            for c in self.api_call_log:
                cache_parts = []
                if c["cache_read"]:
                    cache_parts.append(f"cr={c['cache_read']:,}")
                if c["cache_create"]:
                    cache_parts.append(f"cw={c['cache_create']:,}")
                cache_str = f" [{', '.join(cache_parts)}]" if cache_parts else ""
                lines.append(
                    f"  #{c['call_number']} T{c['turn']} {c['call_type']:<30s} "
                    f"{c['model']:<28s} "
                    f"{c['input_tokens']:>7,} in / {c['output_tokens']:>7,} out"
                    f"{cache_str}  ${c['cost_usd']:.4f}"
                )
        return "\n".join(lines)

    def format_toolbar(self, *, budget_usd: float = 0.0) -> str:
        """One-line cost summary for the CLI status bar."""
        if budget_usd > 0:
            pct = self.total_cost_usd / budget_usd * 100
            parts = [f"${self.total_cost_usd:.3f}/${budget_usd:.2f} ({pct:.0f}%)"]
        else:
            parts = [f"${self.total_cost_usd:.3f}"]
        parts.append(f"T{self.total_turns}")
        parts.append(f"{self.total_input_tokens:,} in")
        parts.append(f"{self.total_output_tokens:,} out")

        total_input = self.total_input_tokens + self.total_cache_read_tokens
        if total_input > 0 and self.total_cache_read_tokens > 0:
            hit_rate = self.total_cache_read_tokens / total_input * 100
            parts.append(f"cache {hit_rate:.0f}%")

        if self.context_tokens > 0:
            parts.append(f"ctx {self.context_tokens:,}tok/{self.context_messages}msg")

        if self.model:
            parts.append(_short_model_name(self.model))

        return " \u2502 ".join(parts)


def _short_model_name(model: str) -> str:
    """Shorten model ID for toolbar display."""
    for prefix in ("claude-", "anthropic/"):
        if model.startswith(prefix):
            model = model[len(prefix):]
    # Strip date suffix (-YYYYMMDD)
    if len(model) > 9 and model[-8:].isdigit() and model[-9] == "-":
        model = model[:-9]
    return model
