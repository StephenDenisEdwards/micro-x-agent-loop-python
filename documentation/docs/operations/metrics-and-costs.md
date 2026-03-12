# Metrics and Cost Tracking Guide

How to monitor agent costs and interpret metrics output.

## Overview

When `MetricsEnabled=true` (default), the agent emits structured metrics to `metrics.jsonl` — one JSON object per line. These track API calls, tool executions, compaction events, and session summaries.

## Viewing Costs During a Session

Use the `/cost` command:

```
you> /cost
```

This displays:
- **Session totals** — total input/output tokens and estimated cost
- **Per-call breakdown** — each API call with token counts, cost, and call type

Call types:
| Type | Meaning |
|------|---------|
| `main` | Primary LLM call for the agent turn |
| `stage2_classification` | Mode analysis Stage 2 LLM call |
| `compaction` | Conversation compaction LLM call |
| `summarization` | Tool result summarization LLM call |

## Reconciling Costs Against Anthropic Billing

Use `/cost reconcile` to compare locally estimated costs against actual Anthropic billing data:

```
you> /cost reconcile                              # Compare today's costs
you> /cost reconcile 7                            # Compare past 7 days (including today)
you> /cost reconcile 30                           # Compare past 30 days
you> /cost reconcile --start 2026-03-01           # From March 1st to today
you> /cost reconcile --start 2026-03-01 --end 2026-03-10   # Specific date range
you> /cost reconcile --end 2026-03-10             # Past 1 day ending March 10th
```

Dates are inclusive and use `YYYY-MM-DD` format. `--from`/`--to` are accepted as aliases for `--start`/`--end`.

This produces a side-by-side table:

```
Cost Reconciliation: 2026-03-11 to 2026-03-12
------------------------------------------------------------
Date         Model                               Ours    Anthropic     Diff Status
------------------------------------------------------------
2026-03-11   sonnet-4-5-20250929                $0.1234   $0.1280    3.6%  OK
2026-03-11   haiku-4-5-20251001                 $0.0089   $0.0092    3.4%  OK
------------------------------------------------------------
TOTAL                                           $0.1323   $0.1372
Overall divergence: 3.6% — OK
```

Rows exceeding 5% divergence are flagged as `MISMATCH`.

**Prerequisites:**
- `MemoryEnabled=true` — local events must be stored in SQLite
- `MetricsEnabled=true` — metrics must be collected
- `anthropic-admin` MCP server configured and running
- `ANTHROPIC_ADMIN_API_KEY` environment variable set

If any prerequisite is missing, the command prints a specific error message explaining what to configure.

## Metrics Persistence

Cost metrics are persisted in two places for durability:

| Destination | Type | Survives Rotation | Queryable |
|---|---|---|---|
| `metrics.jsonl` | Log file (JSON lines) | No (rotates at 10 MB) | Via jq or analyze_costs CLI |
| SQLite events table | Database | Yes | Via SQL or `/cost reconcile` |

Three event types are stored in the events table:

| Event Type | When | Key Data |
|---|---|---|
| `metric.api_call` | After every LLM call | model, tokens, estimated_cost_usd |
| `metric.compaction` | After compaction | tokens_before/after, compaction_cost_usd |
| `metric.session_summary` | On agent shutdown | total_turns, total_cost_usd, model_subtotals |

You can query events directly:

```bash
# Recent API call costs
sqlite3 .micro_x/memory.db "SELECT payload_json FROM events WHERE type = 'metric.api_call' ORDER BY created_at DESC LIMIT 5;"

# Total estimated cost over past 7 days
sqlite3 .micro_x/memory.db "
  SELECT SUM(json_extract(payload_json, '$.estimated_cost_usd'))
  FROM events
  WHERE type = 'metric.api_call'
  AND created_at >= datetime('now', '-7 days');
"
```

## Metrics File Format

Each line in `metrics.jsonl` is a JSON object with a `type` field:

### api_call

Emitted after every LLM API call.

```json
{
  "type": "api_call",
  "session_id": "abc-123",
  "turn_number": 3,
  "call_type": "main",
  "model": "claude-sonnet-4-5-20250929",
  "input_tokens": 4521,
  "output_tokens": 312,
  "cache_creation_input_tokens": 1200,
  "cache_read_input_tokens": 3000,
  "cost_usd": 0.0089,
  "timestamp": "2026-03-04T10:30:00Z"
}
```

### tool_execution

Emitted after every tool call.

```json
{
  "type": "tool_execution",
  "session_id": "abc-123",
  "turn_number": 3,
  "tool_name": "gmail_search",
  "result_chars": 12450,
  "duration_ms": 1230.5,
  "is_error": false,
  "was_summarized": false,
  "timestamp": "2026-03-04T10:30:01Z"
}
```

### compaction

Emitted when conversation compaction occurs.

```json
{
  "type": "compaction",
  "session_id": "abc-123",
  "turn_number": 8,
  "tokens_before": 45000,
  "tokens_after": 12000,
  "messages_compacted": 14,
  "input_tokens": 45000,
  "output_tokens": 3000,
  "cost_usd": 0.015,
  "timestamp": "2026-03-04T10:35:00Z"
}
```

### session_summary

Emitted once at session shutdown.

```json
{
  "type": "session_summary",
  "session_id": "abc-123",
  "total_turns": 12,
  "total_input_tokens": 89000,
  "total_output_tokens": 4500,
  "total_cost_usd": 0.142,
  "total_api_calls": 15,
  "total_tool_calls": 23,
  "tool_error_count": 1,
  "tool_call_counts": {
    "gmail_search": 5,
    "web_fetch": 3,
    "bash": 15
  },
  "timestamp": "2026-03-04T11:00:00Z"
}
```

## Analysing Costs

### Using analyze_costs.py

```bash
python -m micro_x_agent_loop.analyze_costs metrics.jsonl
```

This provides summary statistics across sessions.

### Manual Analysis with jq

```bash
# Total cost across all sessions
cat metrics.jsonl | jq -s '[.[] | select(.type=="session_summary") | .total_cost_usd] | add'

# Most expensive sessions
cat metrics.jsonl | jq -s '[.[] | select(.type=="session_summary")] | sort_by(-.total_cost_usd) | .[:5] | .[] | {session_id, total_cost_usd, total_turns}'

# Tool call frequency
cat metrics.jsonl | jq -s '[.[] | select(.type=="tool_execution") | .tool_name] | group_by(.) | map({tool: .[0], count: length}) | sort_by(-.count)'

# Average cost per turn
cat metrics.jsonl | jq -s '[.[] | select(.type=="session_summary")] | map(.total_cost_usd / .total_turns) | add / length'

# Cache hit rate (Anthropic only)
cat metrics.jsonl | jq -s '[.[] | select(.type=="api_call" and .cache_read_input_tokens > 0)] | length as $cached | [.[] | select(.type=="api_call")] | length as $total | {cached: $cached, total: $total, hit_rate: ($cached / $total * 100)}'
```

## Cost Reduction Features

The agent has several cost reduction features (ADR-012):

| Feature | Config Key | Effect |
|---------|-----------|--------|
| Prompt caching | `PromptCachingEnabled` | Cache system prompt + tool definitions (Anthropic only) |
| Conversation compaction | `CompactionStrategy: "summarize"` | Summarise old messages to reduce context length |
| Smart compaction trigger | `SmartCompactionTriggerEnabled` | Trigger compaction based on actual token usage |
| Concise output mode | `ConciseOutputEnabled` | Instruct LLM to produce shorter responses |
| Mode analysis | `ModeAnalysisEnabled` | Detect compiled tasks to avoid expensive prompt-mode execution |

See [Prompt Caching Cost Analysis](prompt-caching-cost-analysis.md) for measured savings.

## Related

- [Configuration Reference](config.md)
- [Prompt Caching Cost Analysis](prompt-caching-cost-analysis.md)
- [ADR-012: Layered Cost Reduction Architecture](../architecture/decisions/ADR-012-layered-cost-reduction-architecture.md)
- [Cost Metrics Design](../design/DESIGN-cost-metrics.md)
- [Manual Test: Cost Reconciliation](../testing/MANUAL-TEST-cost-reconciliation.md)
- [Manual Test: Pricing](../testing/MANUAL-TEST-pricing.md)
