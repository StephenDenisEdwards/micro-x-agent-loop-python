# Design: Token Budget Tool Result Compaction

## Problem

Each Anthropic API call sends the full conversation history as input. Tool results — especially from Gmail (raw HTML) and LinkedIn (full page content) — can be very large. Over multiple tool calls, input tokens grow unboundedly:

```
Turn 1: 2K input tokens
Turn 3: 12K input tokens (after gmail_read)
Turn 5: 28K input tokens (after linkedin_jobs)
Turn 7: 53K input tokens → rate limit hit
```

The LLM rarely needs old tool results verbatim after it has already processed them and responded. But those results stay in the conversation history at full size forever.

## Approaches Considered

### 1. Truncate Immediately After Use

After the LLM responds to a tool result, immediately truncate it. Simple but aggressive — it degrades all conversations equally, even short ones where token growth isn't a problem.

### 2. LLM-Generated Summaries

Ask the LLM to summarize old tool results into compact representations. Preserves more semantic information but adds extra API calls, latency, and code complexity. The cost of the summary calls could offset the savings.

### 3. Token Budget Threshold (Chosen)

Only truncate old tool results when a budget is exceeded. This is the least invasive approach:

- Short conversations: zero impact
- Long conversations: gradual, targeted reduction
- No extra API calls
- Simple implementation

## Implementation

### Trigger Condition

After each `stream_chat()` call, the agent checks:

```python
if self._input_token_budget > 0 and input_tokens > self._input_token_budget:
    self._compact_old_tool_results(input_tokens)
```

### What Gets Compacted

The `_compact_old_tool_results()` method:

1. Finds all tool-result messages — messages where `role == "user"` and `content` is a list of `tool_result` dicts
2. Skips the **most recent** tool-result message (the LLM may still need it for the current turn)
3. For each older tool-result block:
   - Skips if content is not a string
   - Skips if already truncated (ends with the marker)
   - Skips if content is already shorter than the retention limit
   - Truncates to `tool_result_retention_chars` characters
   - Appends `[truncated for context management]` so the LLM knows what happened

### Idempotency

The truncation marker check (`content.endswith(marker)`) ensures that already-compacted results are not re-truncated. This means the method can be called on every turn without accumulating markers.

### Diagnostics

When compaction occurs, a message is printed to stderr:

```
Note: Compacted 3 old tool result(s) — input tokens (45,231) exceeded budget (40,000)
```

### Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `InputTokenBudget` | `40000` | Input token threshold that triggers compaction. Set to `0` to disable. |
| `ToolResultRetentionChars` | `500` | Characters to keep from each old tool result after compaction. |

### Data Flow

```
stream_chat() returns input_tokens
    │
    ▼
input_tokens > budget?
    │ no → do nothing
    │ yes ▼
Find tool-result messages
    │
    ▼
Skip most recent tool-result message
    │
    ▼
For each older tool-result block:
    - Skip if already truncated
    - Skip if short enough
    - Truncate to retention_chars + marker
    │
    ▼
Print diagnostic to stderr
```
