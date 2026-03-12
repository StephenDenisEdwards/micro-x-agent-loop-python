# Design: Cost Metrics Logging

## Status

**Implemented** — structured metrics pipeline across all providers, with session accumulation, REPL command, and analysis CLI.

## Problem

The agent had no structured cost metrics. Token usage was logged as human-readable DEBUG strings, Anthropic cache metrics were available but discarded, OpenAI logged no token data at all, and there was no timing, cost calculation, or session aggregation. This made it impossible to measure cost reduction ROI.

## Solution

A full metrics pipeline: `UsageResult` dataclass normalising usage across providers, timing at every API call and tool execution, structured JSON metric emission via loguru, in-session cost summary via `/cost`, and a standalone analysis CLI.

## Architecture

```
Provider (Anthropic/OpenAI)
  │  returns UsageResult with tokens, timing, cache metrics
  ▼
TurnEngine
  │  emits api_call and tool_execution callbacks
  ▼
Agent
  │  accumulates into SessionAccumulator
  │  builds metric records
  │  calls emit_metric()
  ▼
metrics.py → loguru sink (metrics=True) → metrics.jsonl

            /cost command → reads SessionAccumulator → prints summary
            analyze_costs.py → reads metrics.jsonl → prints/compares reports
```

## Components

### UsageResult (`usage.py`)

Frozen dataclass normalising token usage across providers:

| Field | Type | Description |
|-------|------|-------------|
| `input_tokens` | int | Prompt tokens sent |
| `output_tokens` | int | Completion tokens received |
| `cache_creation_input_tokens` | int | Tokens written to cache (Anthropic) |
| `cache_read_input_tokens` | int | Tokens read from cache (Anthropic/OpenAI) |
| `duration_ms` | float | Wall-clock time for the API call |
| `time_to_first_token_ms` | float | Time to first streamed token |
| `provider` | str | `"anthropic"` or `"openai"` |
| `model` | str | Model ID used |
| `message_count` | int | Number of messages in the request |
| `tool_schema_count` | int | Number of tool schemas in the request |
| `stop_reason` | str | Why the response ended |

**PRICING dict** — maps model IDs to per-million-token costs as `(input, output, cache_read, cache_create)` tuples. Loaded at startup from the `Pricing` section of `config.json` via `load_pricing_overrides()`. No hardcoded defaults — all pricing data lives in config.

**`estimate_cost(usage)`** — calculates USD from a `UsageResult`. Returns `0.0` for unknown models (with a one-time warning logged per model).

### Metrics Emission (`metrics.py`)

**`emit_metric(record)`** — serialises a dict to JSON and writes it to a loguru sink bound with `metrics=True`.

Four metric builders produce structured records:

| Builder | Metric Type | Key Fields |
|---------|-------------|------------|
| `build_api_call_metric` | `api_call` | tokens, cache, timing, cost, session/turn context |
| `build_tool_execution_metric` | `tool_execution` | tool name, result size, duration, error flag |
| `build_compaction_metric` | `compaction` | tokens before/after, freed, compaction cost |
| `build_session_summary_metric` | `session_summary` | totals from SessionAccumulator |

**`SessionAccumulator`** — mutable dataclass that sums tokens, cost, tool calls, and duration across a session. Provides `format_summary()` for the `/cost` command.

### MetricsLogConsumer (`logging_config.py`)

A new log consumer type (`"metrics"`) that registers a loguru sink with:
- Filter: `record["extra"].get("metrics")` — only captures metrics records
- Format: `"{message}"` — raw JSON, one record per line
- Default path: `metrics.jsonl`
- Rotation: 10 MB, retention: 3 files

Registered in `_CONSUMER_TYPES` alongside `"console"` and `"file"`.

### Provider Changes

Both providers now return `UsageResult` from every API call:

**`stream_chat` return type:** `tuple[dict, list[dict], str, UsageResult]` (was 3-tuple)

**`create_message` return type:** `tuple[str, UsageResult]` (was `str`)

#### Anthropic Provider

- Wraps API calls with `time.monotonic()` for duration
- Tracks `t_first_token` on first `content_block_delta` for TTFT
- Extracts `cache_creation_input_tokens` and `cache_read_input_tokens` from `response.usage` via `getattr` with fallback to 0

#### OpenAI Provider

- Adds `stream_options: {"include_usage": True}` to streaming kwargs
- Handles the final usage-only chunk where `chunk.usage` is populated
- Maps `prompt_tokens` → `input_tokens`, `completion_tokens` → `output_tokens`
- Extracts `prompt_tokens_details.cached_tokens` for cache read metrics
- Same timing instrumentation as Anthropic

### TurnEngine Changes

Two new optional callbacks:
- `on_api_call_completed(usage: UsageResult, call_type: str)` — called after every `stream_chat`
- `on_tool_executed(tool_name: str, result_chars: int, duration_ms: float, is_error: bool)` — called after every tool execution

Tool execution is now timed with `time.monotonic()`, including error cases.

### Compaction Changes

- `_summarize()` now returns `tuple[str, UsageResult]` instead of `str`
- `SummarizeCompactionStrategy` accepts an optional `on_compaction_completed` callback
- After successful compaction, the callback receives `(usage, tokens_before, tokens_after, messages_compacted)`

### Agent Integration

- `_turn_number` counter incremented on each `_run_inner()`
- `_session_accumulator` tracks all costs for the session
- Wires `on_api_call_completed` and `on_tool_executed` to TurnEngine
- Wires `on_compaction_completed` to `SummarizeCompactionStrategy` (via direct attribute set)
- On `shutdown()`, emits a `session_summary` metric
- Routes `/cost` command to `_handle_cost_command` which prints `SessionAccumulator.format_summary()`

### Configuration

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `MetricsEnabled` | bool | `true` | Enables metrics collection and emission |

When `MetricsEnabled=false`, no callbacks are wired and no metrics are emitted.

To capture metrics to a file, add the metrics log consumer:

```json
{
  "LogConsumers": [
    {"type": "console"},
    {"type": "file", "path": "agent.log"},
    {"type": "metrics", "path": "metrics.jsonl"}
  ]
}
```

### `/cost` Command

Available always (not gated by `MemoryEnabled`). Prints the current session's accumulated cost summary:

```
Session Cost Summary
--------------------
Total API calls:    12
Total turns:        5
Input tokens:       45,230
Output tokens:      8,120
Cache read tokens:  12,000
Cache create tokens:3,200
Total cost:         $0.234500
Total duration:     15,432 ms
Tool calls:         8 (1 errors)
Compaction events:  1
Tool breakdown:
  bash: 4
  read_file: 3
  write_file: 1
```

### Analysis CLI (`analyze_costs.py`)

Standalone batch analysis tool using only stdlib:

```bash
python -m micro_x_agent_loop.analyze_costs --file metrics.jsonl
python -m micro_x_agent_loop.analyze_costs --session <id>
python -m micro_x_agent_loop.analyze_costs --since 2026-02-26T00:00:00
python -m micro_x_agent_loop.analyze_costs --compare <session_a> <session_b>
python -m micro_x_agent_loop.analyze_costs --csv
```

Features:
- Aggregates `api_call`, `tool_execution`, and `compaction` records
- Session and time-range filtering
- Side-by-side session comparison with delta calculation
- CSV output for spreadsheet import

### SQLite Event Persistence

In addition to the loguru metrics sink, all cost metrics are dual-written to the SQLite events table via the `MemoryFacade.emit_event()` method. This ensures metrics survive log rotation and are queryable for reconciliation.

Three event types are persisted:

| Event Type | When Emitted | Key Payload Fields |
|---|---|---|
| `metric.api_call` | After every LLM API call | model, input/output tokens, cache tokens, estimated_cost_usd |
| `metric.compaction` | After conversation compaction | tokens_before/after, tokens_freed, compaction_cost_usd |
| `metric.session_summary` | On agent shutdown | total_turns, total_cost_usd, model_subtotals |

The `ActiveMemoryFacade` stores a reference to the `MemoryStore` (exposed via the `store` property) so that downstream consumers like cost reconciliation can query events directly.

**Data flow:**

```
Agent callback (on_api_call_completed / on_compaction_completed / shutdown)
  │
  ├─► emit_metric() ──► loguru sink ──► metrics.jsonl
  │
  └─► memory.emit_event() ──► EventEmitter ──► SQLite events table
```

### Cost Reconciliation (`cost_reconciliation.py`)

Compares locally estimated costs (from `metric.api_call` events in SQLite) against actual billed costs from the Anthropic billing API.

**Components:**

| Function | Purpose |
|---|---|
| `_load_local_costs(store, start, end)` | Queries `metric.api_call` events, groups by date and model |
| `_parse_anthropic_cost_response(text)` | Parses the Anthropic cost report JSON into `{date: {model: cost}}` |
| `reconcile_costs(tool_map, store, days)` | Orchestrates: loads local data, calls Anthropic API, builds comparison |

**Invocation:** `/cost reconcile [days]` (default: 1 day lookback).

The reconciliation uses the `anthropic-admin__anthropic_usage` MCP tool with:
- `action: "cost"` — queries the `/v1/organizations/cost_report` endpoint
- `bucket_width: "1d"` — daily granularity
- `group_by: ["model"]` — per-model breakdown

A divergence threshold of 5% is used to flag mismatches. The output is a formatted table showing per-model/date comparison with OK/MISMATCH status.

**Prerequisites:**
- `MemoryEnabled=true` (for local event data)
- `anthropic-admin` MCP server running with `ANTHROPIC_ADMIN_API_KEY`
- At least one session with `metric.api_call` events in the lookback period

## What This Enables

- **Baseline cost per session** — measure before optimisation
- **Cache hit rate analysis** — compare `cache_read_input_tokens` vs `input_tokens`
- **Compaction ROI** — compare `compaction_cost_usd` vs `tokens_freed` value
- **Tool cost ranking** — identify which tools produce the most input tokens
- **Model comparison** — A/B test models with `--compare`
- **Latency vs cost** — correlate `duration_ms` with cost changes
- **Retry waste** — identify `max_tokens` retries in `stop_reason`

## Files

| File | Action |
|------|--------|
| `src/micro_x_agent_loop/usage.py` | **Created** — UsageResult, PRICING, estimate_cost |
| `src/micro_x_agent_loop/metrics.py` | **Created** — emit_metric, builders, SessionAccumulator |
| `src/micro_x_agent_loop/cost_reconciliation.py` | **Created** — reconcile local vs Anthropic billed costs |
| `src/micro_x_agent_loop/analyze_costs.py` | **Created** — CLI analysis module |
| `src/micro_x_agent_loop/logging_config.py` | Modified — MetricsLogConsumer |
| `src/micro_x_agent_loop/provider.py` | Modified — updated return types |
| `src/micro_x_agent_loop/providers/anthropic_provider.py` | Modified — timing, cache extraction, UsageResult |
| `src/micro_x_agent_loop/providers/openai_provider.py` | Modified — stream_options, usage chunks, timing, UsageResult |
| `src/micro_x_agent_loop/compaction.py` | Modified — tuple return, compaction callback |
| `src/micro_x_agent_loop/turn_engine.py` | Modified — new callbacks, tool timing |
| `src/micro_x_agent_loop/commands/command_handler.py` | Modified — /cost reconcile subcommand |
| `src/micro_x_agent_loop/commands/router.py` | Modified — /cost dispatch |
| `src/micro_x_agent_loop/agent_config.py` | Modified — metrics_enabled, memory_store fields |
| `src/micro_x_agent_loop/app_config.py` | Modified — MetricsEnabled parsing |
| `src/micro_x_agent_loop/bootstrap.py` | Modified — passes metrics_enabled, memory_store |
| `src/micro_x_agent_loop/agent.py` | Modified — accumulator, callbacks, /cost, shutdown emit, event persistence |
| `src/micro_x_agent_loop/memory/facade.py` | Modified — store property, emit_event method |
| `tests/test_usage.py` | **Created** — 38 tests including per-model coverage |
| `tests/test_metrics.py` | **Created** |
| `tests/providers/test_anthropic_provider.py` | Modified — 4-tuple, UsageResult assertions |
| `tests/providers/test_openai_provider.py` | Modified — usage chunks, 4-tuple |
| `tests/test_llm_client_stream.py` | Modified — 4-tuple |
| `tests/test_compaction_strategy.py` | Modified — tuple return, callback test |
| `tests/agent/test_agent_commands.py` | Modified — UsageResult in mocks, /cost test |
