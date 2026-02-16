# ADR-005: Token Budget Threshold for Tool Result Compaction

## Status

Accepted

## Context

The agent loop accumulates tool results (Gmail HTML bodies, LinkedIn page content) in conversation history. Every API call resends ALL previous messages, so input tokens grow unboundedly as tools are used. In multi-tool workflows like job searching, input tokens reached 53K+, triggering Anthropic rate limits and increasing costs.

Two existing mechanisms were too blunt:

- **`MaxToolResultChars`** — truncates each tool result at ingestion time, but can't distinguish between results the LLM still needs and stale results from earlier turns
- **`MaxConversationMessages`** — drops entire messages from the front, losing both tool results and user/assistant context indiscriminately

Three approaches were considered:

1. **Truncate immediately after use** — truncate tool results right after the LLM's next response. This degrades all conversations, even short ones that don't need it.
2. **LLM-generated summaries** — ask the LLM to summarize old tool results. This adds extra API calls, latency, and complexity.
3. **Token budget threshold** — only truncate old tool results when input tokens exceed a configurable budget. Simple conversations are completely unaffected.

## Decision

Implement a **token budget threshold** approach:

- After each API response, check if `input_tokens > InputTokenBudget`
- If over budget, truncate the content of all tool-result messages **except the most recent one** to `ToolResultRetentionChars` characters, appending `[truncated for context management]`
- The compaction is **idempotent** — already-truncated results are skipped
- A diagnostic message is printed to stderr when compaction occurs
- Set `InputTokenBudget` to `0` to disable compaction entirely

Default values: `InputTokenBudget = 40000`, `ToolResultRetentionChars = 500`.

## Consequences

**Easier:**
- Long-running, tool-heavy workflows stay within token limits without manual intervention
- Simple conversations are completely unaffected (budget never exceeded)
- Minimal code change — no extra API calls, no new dependencies
- The LLM retains the most recent tool result in full for accurate responses
- Old tool results retain their first 500 characters, preserving some context

**Harder:**
- If the LLM needs to reference a much older tool result, it will only see the truncated version
- Character-based truncation is an approximation of token usage (but good enough in practice)
- Users need to understand two new config settings if they want to tune behavior
