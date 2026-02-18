# Tool: anthropic_usage

Query Anthropic Admin API for organization usage and cost reports.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | Yes | Which report: `"usage"` (token usage), `"cost"` (spend in USD), `"claude_code"` (productivity metrics) |
| `starting_at` | string | Yes | Start time — RFC 3339 for usage/cost (e.g. `"2025-02-01T00:00:00Z"`), `YYYY-MM-DD` for claude_code |
| `ending_at` | string | No | End time (same format as `starting_at`) |
| `bucket_width` | string | No | Time granularity: `"1m"`, `"1h"`, or `"1d"` (usage supports all three; cost only supports `"1d"`) |
| `group_by` | array | No | Group results by fields (e.g. `["model", "workspace_id"]` for usage; `["workspace_id", "description"]` for cost) |
| `limit` | number | No | Max number of time buckets / records to return |

## Actions

### `usage` — Token Usage Report

Calls `GET /v1/organizations/usage_report/messages`. Returns token-level usage data with input/output token counts per time bucket. Data freshness ~5 minutes.

### `cost` — Cost Report

Calls `GET /v1/organizations/cost_report`. Returns cost breakdown in USD (amounts in cents). Only supports `"1d"` bucket width. Priority Tier costs are excluded.

### `claude_code` — Claude Code Productivity Metrics

Calls `GET /v1/organizations/usage_report/claude_code`. Returns per-user, per-day records including sessions, LOC added/removed, commits, PRs, tool acceptance rates, token usage by model, and estimated cost. Data freshness ~1 hour.

## Behavior

- Uses `httpx.AsyncClient` for async HTTP requests
- Authenticates with `x-api-key` header and `anthropic-version: 2023-06-01`
- Builds query params from input, handling `group_by` as repeated `group_by[]` params
- Returns pretty-printed JSON prefixed with a report type header
- Returns error strings on HTTP failures (never raises)
- **Conditional registration:** Only available when `ANTHROPIC_ADMIN_API_KEY` is set in `.env`

## Implementation

- Source: `src/micro_x_agent_loop/tools/anthropic/anthropic_usage_tool.py`
- Uses `httpx` for direct HTTP calls (Anthropic SDKs do not cover Admin API)
- Base URL: `https://api.anthropic.com/v1/organizations`

## Example

```
you> How much have I spent on the Anthropic API this month?
```

Claude calls:
```json
{
  "name": "anthropic_usage",
  "input": {
    "action": "cost",
    "starting_at": "2026-02-01T00:00:00Z",
    "bucket_width": "1d"
  }
}
```

```
you> Show my token usage for the past week grouped by model
```

Claude calls:
```json
{
  "name": "anthropic_usage",
  "input": {
    "action": "usage",
    "starting_at": "2026-02-11T00:00:00Z",
    "bucket_width": "1d",
    "group_by": ["model"]
  }
}
```

## Authentication

Requires an Anthropic Admin API key (`sk-ant-admin...`), which is separate from the inference API key. Admin keys are created by organization admins in the Anthropic Console under Settings > Admin Keys. See the [design doc](../../DESIGN-account-management-apis.md) for full API details.
