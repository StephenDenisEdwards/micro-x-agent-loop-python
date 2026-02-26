# Plan: Cost Metrics Logging

## Status

**Planning** — Analysis of current logging gaps and design for structured cost metrics.

## Problem

To measure the ROI of cost reduction levers (see [PLAN-cost-reduction.md](PLAN-cost-reduction.md)), we need structured, machine-parseable metrics from every API call, tool execution, and compaction event. The current logging is human-readable DEBUG strings that lack key fields, making cost analysis impossible.

## Metrics Required

To evaluate every lever in the cost reduction plan, we need the following metrics at three levels.

### Per API Call Metrics

| Metric | Needed For (Cost Lever) | Currently Logged? |
|--------|------------------------|-------------------|
| `session_id` | All — correlate calls to sessions | **No** |
| `turn_number` | All — identify per-turn cost | **No** |
| `call_type` | #2 Compaction model — distinguish main vs compaction | **Partial** (separate log lines but no structured field) |
| `model` | #5 Model routing, #10 Arbitrage | Yes (DEBUG string) |
| `provider` | #10 Arbitrage | **No** |
| `input_tokens` | #1 Caching, #3 Tool results, #4 Compaction trigger | **Anthropic only** (DEBUG string) |
| `output_tokens` | #9 Output reduction | **Anthropic only** (DEBUG string) |
| `cache_creation_input_tokens` | #1 Prompt caching | **No** (Anthropic provides this but we don't log it) |
| `cache_read_input_tokens` | #1 Prompt caching | **No** (Anthropic provides this but we don't log it) |
| `message_count` | #4 Compaction trigger | Yes (DEBUG string) |
| `tool_schema_count` | #7 Tool schema optimisation | Yes (DEBUG string) |
| `stop_reason` | General diagnostics | Yes (DEBUG string) |
| `duration_ms` | Latency impact of cost changes | **No** |
| `time_to_first_token_ms` | Latency impact of caching | **No** |
| `estimated_cost_usd` | #8 Cost tracking | **No** |
| `is_retry` | #12 Retry cost | **No** |
| `retry_attempt` | #12 Retry cost | **No** |

### Per Tool Execution Metrics

| Metric | Needed For (Cost Lever) | Currently Logged? |
|--------|------------------------|-------------------|
| `tool_name` | #3 Tool result size reduction | **No** (only on truncation) |
| `result_chars` | #3 Tool result size reduction | **No** (only on truncation) |
| `result_estimated_tokens` | #3 Tool result size reduction | **No** |
| `was_truncated` | #3 Tool result size reduction | Yes (WARNING on truncation) |
| `original_chars` | #3 Tool result size reduction | Yes (only on truncation) |
| `execution_duration_ms` | General diagnostics | **No** |
| `is_error` | General diagnostics | Recorded in memory DB, not in logs |

### Per Compaction Event Metrics

| Metric | Needed For (Cost Lever) | Currently Logged? |
|--------|------------------------|-------------------|
| `estimated_tokens_before` | #4 Compaction trigger | Yes (INFO string) |
| `estimated_tokens_after` | #4 Compaction trigger | Derivable |
| `tokens_freed` | #4 Compaction trigger | Yes (INFO string) |
| `messages_compacted` | #4 Compaction trigger | Yes (INFO string) |
| `compaction_input_tokens` | #2 Compaction model cost | **Anthropic only** (DEBUG string in provider) |
| `compaction_output_tokens` | #2 Compaction model cost | **Anthropic only** (DEBUG string in provider) |
| `compaction_model` | #2 Compaction model | **Partial** (logged in provider, not in compaction) |
| `compaction_cost_usd` | #2 Compaction model cost | **No** |
| `net_saving_tokens` | #2, #4 ROI calculation | **No** |

### Per Session Aggregate Metrics

| Metric | Needed For (Cost Lever) | Currently Logged? |
|--------|------------------------|-------------------|
| `total_input_tokens` | All | **No** |
| `total_output_tokens` | All | **No** |
| `total_cache_read_tokens` | #1 Caching | **No** |
| `total_cache_creation_tokens` | #1 Caching | **No** |
| `total_cost_usd` | #8 Budgeting | **No** |
| `total_turns` | General | **No** |
| `total_compaction_events` | #4 Compaction | **No** |
| `tool_call_counts` (by name) | #3, #7 Tool analysis | **No** |
| `tool_result_total_chars` (by name) | #3 Tool result analysis | **No** |

---

## Current Logging Audit

### What exists

```
# Anthropic provider — stream_chat
DEBUG | API request: model=claude-sonnet-4-5-20250929, max_tokens=32768, messages=12, tools=15
DEBUG | API response: stop_reason=end_turn, input_tokens=8432, output_tokens=1204

# Anthropic provider — create_message (compaction)
DEBUG | Compaction API request: model=claude-sonnet-4-5-20250929, messages=1
DEBUG | Compaction API response: input_tokens=24510, output_tokens=2048

# Compaction strategy
INFO  | Compaction: estimated ~85,000 tokens, threshold 80,000 — compacting 18 messages
INFO  | Compaction: summarized 18 messages into ~2,048 tokens, freed ~72,000 estimated tokens

# Turn engine — truncation only
WARNING | linkedin_job_detail output truncated from 52,340 to 40,000 chars

# Agent — trim only
INFO  | Conversation history trimmed - removed 4 oldest message(s)...
```

### Critical gaps

1. **OpenAI provider logs zero token usage.** The streaming response doesn't include usage by default. Fix: add `stream_options={"include_usage": True}` to the API call. The non-streaming `create_message` has `response.usage` available but doesn't log it.

2. **Anthropic cache metrics are available but not captured.** The `response.usage` object includes `cache_creation_input_tokens` and `cache_read_input_tokens` when prompt caching is active. These are silently discarded.

3. **No structured format.** All metrics are embedded in human-readable f-strings. Parsing them requires regex extraction from log files — fragile and lossy.

4. **No timing.** No `time.monotonic()` calls around API calls or tool executions.

5. **No turn/session context.** API calls can't be correlated to specific user requests or sessions.

6. **No tool result sizes logged routinely.** Only truncation events (WARNING level) are logged — the vast majority of tool results that are under the 40K limit are invisible.

7. **No cost calculation anywhere.** Token counts exist but are never multiplied by prices.

---

## Design

### Approach: Structured JSON Metrics Logger

Add a dedicated metrics logging mechanism that emits structured JSON records. This is separate from the human-readable loguru logs (which remain for debugging). Each record is a self-contained JSON object with a `metric_type` discriminator.

#### Why structured JSON in log files (not SQLite)

- Logs already work — file rotation, retention, and the log pipeline exist
- JSON lines are trivially parseable by `jq`, Python, pandas, or any log aggregator
- No schema migration burden
- Can be analysed offline without running the agent
- The memory SQLite DB could store metrics too, but that couples cost analysis to the memory system being enabled

#### Log sink

A new loguru sink writing JSON lines to a dedicated file (e.g., `metrics.jsonl`), configured alongside existing log consumers. Alternatively, use the existing file log with a `metrics` log level or a filter. The simplest approach: a new `MetricsLogConsumer` in `logging_config.py` that writes JSON lines.

### Metric Record Schemas

#### `api_call`

```json
{
  "metric_type": "api_call",
  "timestamp": "2026-02-26T14:30:00.123Z",
  "session_id": "abc-123",
  "turn_number": 3,
  "call_type": "main",
  "provider": "anthropic",
  "model": "claude-sonnet-4-5-20250929",
  "input_tokens": 8432,
  "output_tokens": 1204,
  "cache_creation_input_tokens": 2100,
  "cache_read_input_tokens": 5800,
  "message_count": 12,
  "tool_schema_count": 15,
  "stop_reason": "end_turn",
  "duration_ms": 3420,
  "time_to_first_token_ms": 890,
  "estimated_cost_usd": 0.0435,
  "is_retry": false,
  "retry_attempt": 0
}
```

#### `tool_execution`

```json
{
  "metric_type": "tool_execution",
  "timestamp": "2026-02-26T14:30:01.500Z",
  "session_id": "abc-123",
  "turn_number": 3,
  "tool_name": "linkedin_job_detail",
  "result_chars": 12450,
  "result_estimated_tokens": 3112,
  "was_truncated": false,
  "original_chars": 12450,
  "execution_duration_ms": 1840,
  "is_error": false
}
```

#### `compaction`

```json
{
  "metric_type": "compaction",
  "timestamp": "2026-02-26T14:31:00.000Z",
  "session_id": "abc-123",
  "turn_number": 5,
  "estimated_tokens_before": 85000,
  "estimated_tokens_after": 13000,
  "tokens_freed": 72000,
  "messages_compacted": 18,
  "compaction_model": "claude-haiku-4-5-20251001",
  "compaction_input_tokens": 24510,
  "compaction_output_tokens": 2048,
  "compaction_cost_usd": 0.0087,
  "net_saving_tokens": 69952
}
```

#### `session_summary` (emitted at session end or on `/session` command)

```json
{
  "metric_type": "session_summary",
  "timestamp": "2026-02-26T15:00:00.000Z",
  "session_id": "abc-123",
  "total_turns": 8,
  "total_input_tokens": 142000,
  "total_output_tokens": 18500,
  "total_cache_read_tokens": 45000,
  "total_cache_creation_tokens": 8000,
  "total_cost_usd": 0.72,
  "total_compaction_events": 2,
  "total_tool_calls": 15,
  "tool_call_counts": {"bash": 4, "linkedin_job_detail": 3, "read_file": 5, "web_fetch": 3},
  "tool_result_total_chars": {"bash": 8200, "linkedin_job_detail": 37500, "read_file": 22000, "web_fetch": 45000}
}
```

### Implementation Changes

#### 1. Provider-agnostic `UsageResult` dataclass

The core abstraction. Define a single dataclass that normalises usage data across all providers. Each provider maps its native response fields into this common shape. The rest of the system (metrics, compaction, cost calculation) only depends on `UsageResult`, never on provider-specific types.

```python
# New file: src/micro_x_agent_loop/usage.py

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class UsageResult:
    """Provider-agnostic usage metadata returned from every LLM API call.

    Each provider is responsible for mapping its native response fields
    into this common shape. Fields that a provider cannot populate are
    left at their defaults (0 / 0.0).
    """

    # --- Token counts (normalised names) ---
    input_tokens: int = 0
    output_tokens: int = 0

    # --- Cache metrics (Anthropic-native; 0 for providers without caching) ---
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    # --- Timing ---
    duration_ms: float = 0.0
    time_to_first_token_ms: float = 0.0

    # --- Provider identity (set by each provider) ---
    provider: str = ""
    model: str = ""

    # --- Request context ---
    message_count: int = 0
    tool_schema_count: int = 0
    stop_reason: str = ""
```

**Provider mapping:**

| `UsageResult` field | Anthropic source | OpenAI source |
|---------------------|-----------------|---------------|
| `input_tokens` | `response.usage.input_tokens` | `response.usage.prompt_tokens` |
| `output_tokens` | `response.usage.output_tokens` | `response.usage.completion_tokens` |
| `cache_creation_input_tokens` | `response.usage.cache_creation_input_tokens` | `0` (not supported) |
| `cache_read_input_tokens` | `response.usage.cache_read_input_tokens` | `response.usage.prompt_tokens_details.cached_tokens` (if available) |
| `duration_ms` | `time.monotonic()` delta | `time.monotonic()` delta |
| `time_to_first_token_ms` | First `content_block_delta` timestamp | First `delta.content` timestamp |
| `provider` | `"anthropic"` | `"openai"` |
| `model` | Passed-in model string | Passed-in model string |

#### 2. Updated `LLMProvider` Protocol (`provider.py`)

```python
from micro_x_agent_loop.usage import UsageResult

class LLMProvider(Protocol):
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
    ) -> tuple[dict, list[dict], str, UsageResult]:
        # Returns (message, tool_blocks, stop_reason, usage)
        ...

    async def create_message(
        self,
        model: str,
        max_tokens: int,
        temperature: float,
        messages: list[dict],
    ) -> tuple[str, UsageResult]:
        # Returns (text, usage) — was just str
        ...
```

**Key change:** `stream_chat` gains a 4th return element. `create_message` returns a tuple instead of a bare string. This is a breaking change to the Protocol — all consumers (TurnEngine, compaction) update in the same PR.

#### 3. Anthropic provider changes (`anthropic_provider.py`)

- **`stream_chat`**: Wrap the API call with `time.monotonic()`. Record TTFT from the first `content_block_delta`. Capture `usage.cache_creation_input_tokens` and `usage.cache_read_input_tokens` (using `getattr` with default 0 for backward compatibility if the response doesn't include them). Build and return `UsageResult`.
- **`create_message`**: Same timing + full usage capture. Return `(text, UsageResult)`.

#### 4. OpenAI provider changes (`openai_provider.py`)

- **`stream_chat`**: Add `stream_options={"include_usage": True}` to the API kwargs. The final streamed chunk includes a `usage` field when this is set. Capture `prompt_tokens` → `input_tokens`, `completion_tokens` → `output_tokens`. Check for `prompt_tokens_details.cached_tokens` → `cache_read_input_tokens`. Add timing. Return `UsageResult`.
- **`create_message`**: Capture `response.usage.prompt_tokens` and `response.usage.completion_tokens`. Return `(text, UsageResult)`.

#### 5. Turn engine changes (`turn_engine.py`)

- Receive `UsageResult` from `stream_chat` (4th return element).
- Pass it to the metrics emitter via a new callback `on_api_call_completed(usage: UsageResult, call_type: str)`.
- Add `time.monotonic()` around each `tool.execute()` call in `run_one`.
- Emit `tool_execution` metric after each tool call with result size and duration.

#### 6. Compaction changes (`compaction.py`)

- `provider.create_message` now returns `(text, UsageResult)` — destructure it.
- Use the `UsageResult` to emit the `compaction` metric with actual compaction call token counts.
- The compaction strategy no longer needs to know which provider it's talking to — `UsageResult` is provider-agnostic.

#### 7. Agent / TurnEngine orchestration

- Maintain a `_turn_number` counter on `Agent`, incremented each time `run()` is called.
- Pass `session_id` and `turn_number` into `TurnEngine` so metrics include them.
- After `stream_chat` returns, emit the `api_call` metric using `UsageResult` fields.
- Maintain a `SessionAccumulator` that sums token counts, cost, tool calls across the session. Emit `session_summary` metric on session end / `/session` command / agent shutdown.

#### 8. Cost calculation utility (in `usage.py`)

```python
# Pricing table (USD per million tokens)
PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-5-20250929": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_create": 3.75},
    "claude-haiku-4-5-20251001":  {"input": 0.25, "output": 1.25, "cache_read": 0.025, "cache_create": 0.3125},
    "gpt-4.1":                    {"input": 2.0, "output": 8.0, "cache_read": 0.50, "cache_create": 2.0},
    "gpt-4.1-mini":               {"input": 0.4, "output": 1.6, "cache_read": 0.10, "cache_create": 0.4},
    "gpt-4.1-nano":               {"input": 0.1, "output": 0.4, "cache_read": 0.025, "cache_create": 0.1},
}

def estimate_cost(usage: UsageResult) -> float:
    """Calculate estimated cost in USD from a UsageResult."""
    prices = PRICING.get(usage.model, {})
    if not prices:
        return 0.0
    return (
        usage.input_tokens * prices.get("input", 0)
        + usage.output_tokens * prices.get("output", 0)
        + usage.cache_read_input_tokens * prices.get("cache_read", 0)
        + usage.cache_creation_input_tokens * prices.get("cache_create", 0)
    ) / 1_000_000
```

Note: `estimate_cost` takes a `UsageResult` directly — the caller doesn't need to know pricing or provider details.

#### 9. Metrics logger (`metrics.py`)

```python
import json
from datetime import datetime, timezone
from loguru import logger

_metrics_logger = logger.bind(metrics=True)


def emit_metric(record: dict) -> None:
    record.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    _metrics_logger.info(json.dumps(record, default=str))
```

#### 10. Metrics log consumer (`logging_config.py`)

Add a `MetricsLogConsumer` that writes to `metrics.jsonl` with a filter that only accepts records with the `metrics=True` binding, using a raw `{message}` format (since the message is already JSON).

### Adding a new provider

With this abstraction, adding a new provider (e.g., Google Gemini, local Ollama) requires:

1. Implement `stream_chat` and `create_message` per the `LLMProvider` Protocol
2. Map the provider's native usage response into `UsageResult` fields
3. Add the provider's model pricing to the `PRICING` table
4. Register in `create_provider()` factory

The metrics layer, cost calculation, compaction, and all downstream consumers work automatically — they only depend on `UsageResult`, not on any provider-specific type.

---

## What This Enables

Once structured metrics are flowing, the following analyses become possible:

| Analysis | Metrics Used | Answers |
|----------|-------------|---------|
| **Baseline cost per session** | `session_summary.total_cost_usd` | What do sessions cost today? |
| **Cache hit rate** | `api_call.cache_read_input_tokens / api_call.input_tokens` | Is prompt caching working? |
| **Cache savings** | Compare `estimated_cost_usd` with vs without cache pricing | How much does caching save? |
| **Compaction ROI** | `compaction.compaction_cost_usd` vs `compaction.tokens_freed × input_price` | Does compaction pay for itself? |
| **Compaction trigger optimality** | `api_call.input_tokens` over time within session | Are we compacting too early/late? |
| **Tool cost ranking** | `tool_execution.result_estimated_tokens` grouped by `tool_name` | Which tools are most expensive? |
| **Tool schema overhead** | `api_call.tool_schema_count` × measured schema size | What % of input cost is schemas? |
| **Output verbosity** | Distribution of `api_call.output_tokens` | Is the model over-generating? |
| **Model comparison** | `api_call.estimated_cost_usd` grouped by `model` | Which model is cheapest for comparable quality? |
| **Retry waste** | `api_call` records where `is_retry=true` | How much do retries cost? |
| **Latency vs cost** | `api_call.duration_ms` correlated with token counts | Does cost reduction hurt latency? |

---

## Analysis Tooling

Structured metrics are only useful if they can be queried. Three layers of analysis tooling, built incrementally in order of value:

### Layer 1: `/cost` REPL command

Immediate in-session visibility. The agent reads `metrics.jsonl` (or the in-memory `SessionAccumulator`) and prints a cost summary without leaving the REPL. This is the layer that changes behaviour — seeing cost per turn in real time makes expensive patterns visible.

**Commands:**

```
/cost                     — current session summary
/cost detail              — per-turn breakdown for current session
/cost tools               — tool cost ranking for current session
```

**Example output:**

```
assistant> Session cost: $0.43 (8 turns, 2 compactions)
  Input:  142,000 tokens ($0.43)  Cache hits: 45,000 (31%)
  Output:  18,500 tokens ($0.28)
  Compaction: 2 calls ($0.02)
  Top tools by input tokens:
    web_fetch         45,000 chars (3 calls)
    linkedin_detail   37,500 chars (3 calls)
    read_file         22,000 chars (5 calls)
```

**Implementation:** Add a `/cost` handler to `CommandRouter` in `agent.py`. For the current session, read directly from the `SessionAccumulator` (no file I/O needed). For historical queries, parse `metrics.jsonl`.

### Layer 2: Python analysis module

Standalone script for before/after comparisons when validating cost reduction levers. Reads `metrics.jsonl`, filters by date range, and produces summary reports.

```
python -m micro_x_agent_loop.analyze_costs                          # summary of all data
python -m micro_x_agent_loop.analyze_costs --session abc-123        # single session deep-dive
python -m micro_x_agent_loop.analyze_costs --since 2026-02-20       # recent sessions
python -m micro_x_agent_loop.analyze_costs --compare 2026-02-20 2026-02-25  # before/after
```

**Reports:**

- **Summary:** total cost, avg cost per session, avg cost per turn, cache hit rate, compaction frequency
- **Session:** per-turn breakdown, tool ranking, compaction events, cache efficiency for a specific session
- **Tool ranking:** total tokens by tool, avg result size, truncation rate
- **Before/after:** side-by-side comparison of two date ranges for any metric
- **CSV export:** `--csv` flag for spreadsheet analysis

**Implementation:** New module `src/micro_x_agent_loop/analyze_costs.py` with a `__main__` entry point. Uses only stdlib (`json`, `csv`, `argparse`, `datetime`) — no pandas dependency. Reads JSONL line-by-line, aggregates into dicts, prints formatted tables.

### Layer 3: Jupyter notebook (optional)

For deeper visual exploration that the script can't answer — time-series trends, distribution plots, correlation analysis. Only reach for this when needed.

**Scope:** A single notebook `documentation/notebooks/cost-analysis.ipynb` with cells for:
- Load `metrics.jsonl` into a pandas DataFrame
- Cost over time (line chart)
- Token distribution by turn (histogram)
- Cache hit rate trend (line chart)
- Tool cost breakdown (bar chart)
- Before/after comparison (grouped bar chart)

**Dependencies:** `pandas`, `matplotlib` — optional dev dependencies only, not required for the agent itself.

### Which analysis answers which question

| Analysis | `/cost` command | Python module | Jupyter |
|----------|:-:|:-:|:-:|
| What did this session cost? | **primary** | | |
| Which tools are most expensive? | **primary** | also | |
| Is prompt caching working? | cache % shown | **primary** (trend) | also |
| Compare cost before/after a change | | **primary** | also |
| Is compaction paying for itself? | | **primary** | also |
| Optimal compaction threshold | | | **primary** |
| Cost trend over weeks | | | **primary** |

---

## Files Changed

| File | Change |
|------|--------|
| **New:** `usage.py` | `UsageResult` dataclass, `estimate_cost()`, `PRICING` table |
| **New:** `metrics.py` | `emit_metric()` helper, metric record builders |
| **New:** `analyze_costs.py` | CLI analysis module with `__main__` entry point |
| `provider.py` | Update `LLMProvider` Protocol: `stream_chat` returns 4-tuple, `create_message` returns `(str, UsageResult)` |
| `providers/anthropic_provider.py` | Map `response.usage` → `UsageResult`, add timing, capture cache fields |
| `providers/openai_provider.py` | Add `stream_options`, map `usage` → `UsageResult`, add timing |
| `turn_engine.py` | Receive `UsageResult` from `stream_chat`, tool execution timing + size metrics |
| `compaction.py` | Destructure `(text, UsageResult)` from `create_message`, emit compaction metric |
| `agent.py` | Turn counter, `SessionAccumulator`, `/cost` command handler, emit session summary on shutdown |
| `commands/router.py` | Register `/cost` command |
| `logging_config.py` | Add `MetricsLogConsumer` for `metrics.jsonl` |
| `agent_config.py` | Add metrics config (enable/disable, output path) |

## Relationship to Cost Reduction Plan

This plan is a **prerequisite** for all cost reduction work. It implements Lever #8 (Cost Tracking & Budgeting) from `PLAN-cost-reduction.md` and provides the measurement infrastructure to validate Levers #1-#7 and #9-#12.

**Recommended execution order:**
1. Implement this metrics plan first (baseline measurement)
2. Run for a few sessions to establish baseline cost data
3. Implement cost reduction levers starting with #1 (prompt caching)
4. Compare before/after metrics to validate ROI
