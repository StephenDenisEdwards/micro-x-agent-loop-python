# Prompt Caching and Per-Turn Cost Behavior

## Overview

A common expectation is that prompt caching should make costs *decrease* over successive turns in a conversation. In practice, **costs rise per turn** even with caching enabled — but caching keeps costs far lower than they would otherwise be.

This document explains why, using real session data.

## How Prompt Caching Works

When `PromptCachingEnabled` is `true` (the default), the system prompt and tool schemas are tagged with `cache_control: {"type": "ephemeral"}` in the Anthropic provider. On subsequent API calls within the cache TTL (~5 minutes), the provider returns these tokens as `cache_read` instead of re-processing them as fresh input.

Cache-read tokens are charged at **10% of the normal input token price** (see [ADR-012](../architecture/decisions/ADR-012-layered-cost-reduction.md), Layer 1).

## What Gets Cached vs. What Grows

Each API call includes:

| Component | Cached? | Behavior over turns |
|-----------|---------|---------------------|
| System prompt | Yes | Constant size |
| Tool schemas | Yes | Constant size |
| Conversation history (messages) | No | **Grows every turn** |

The system prompt and tools are the largest fixed-cost component. Conversation history accumulates user messages, assistant responses, and tool results — all charged at the full input token rate.

## Real Session Example

The following data was captured from a 4-call session using `claude-haiku-4-5-20251001` with `/debug show-api-payload`. The session involved two user prompts ("list my files", then "list my files again, there may be changes"), each requiring a tool call + response — so 4 API calls total.

### API Payload Log

```
Payload #3 (1st API call):
  Model:        claude-haiku-4-5-20251001
  Messages:     1
  Last user msg: list my files
  Tools:        59
  Stop reason:  tool_use
  Response:     [tool_use: filesystem__bash]
  Usage:        in=326 out=56 cache_read=12692
  Cost:         $0.001875

Payload #2 (2nd API call):
  Model:        claude-haiku-4-5-20251001
  Messages:     3
  Last user msg: list my files
  Tools:        59
  Stop reason:  end_turn
  Response:     Files in your documents directory: ...
  Usage:        in=781 out=174 cache_read=12692
  Cost:         $0.002920

Payload #1 (3rd API call):
  Model:        claude-haiku-4-5-20251001
  Messages:     5
  Last user msg: list my files again, there may be changes
  Tools:        59
  Stop reason:  tool_use
  Response:     [tool_use: filesystem__bash]
  Usage:        in=967 out=56 cache_read=12692
  Cost:         $0.002516

Payload #0 (most recent, 4th API call):
  Model:        claude-haiku-4-5-20251001
  Messages:     7
  Last user msg: list my files again, there may be changes
  Tools:        59
  Stop reason:  end_turn
  Response:     Same as before—no changes detected since last listing.
  Usage:        in=1422 out=14 cache_read=12692
  Cost:         $0.002761
```

### Observations

1. **`cache_read` is constant at 12,692 tokens** — the system prompt + 59 tool schemas, served from cache every call.
2. **`in` (uncached input) grows: 326 → 781 → 967 → 1,422** — conversation history accumulating.
3. **Cost rises: $0.0019 → $0.0029 → $0.0025 → $0.0028** — driven by growing uncached input and varying output size.

### Cost Breakdown Per Call

Using Haiku 4.5 pricing: input=$1.00, output=$5.00, cache_read=$0.10 per million tokens.

| Call | Input cost | Output cost | Cache-read cost | Total |
|------|-----------|-------------|----------------|-------|
| 1st  | $0.000326 | $0.000280   | $0.001269      | $0.001875 |
| 2nd  | $0.000781 | $0.000870   | $0.001269      | $0.002920 |
| 3rd  | $0.000967 | $0.000280   | $0.001269      | $0.002516 |
| 4th  | $0.001422 | $0.000070   | $0.001269      | $0.002761 |

The cache-read cost ($0.001269) is the same on every call — a constant floor. The input cost grows as conversation history accumulates.

### What Would It Cost Without Caching?

If those 12,692 tokens were charged at the full input rate ($1.00/MTok) instead of the cache-read rate ($0.10/MTok):

| Call | With caching | Without caching | Savings |
|------|-------------|-----------------|---------|
| 1st  | $0.001875   | $0.013298       | 86%     |
| 2nd  | $0.002920   | $0.014343       | 80%     |
| 3rd  | $0.002516   | $0.013939       | 82%     |
| 4th  | $0.002761   | $0.014184       | 81%     |
| **Total** | **$0.010072** | **$0.055764** | **82%** |

Caching saved **$0.046 across just 4 API calls** — an 82% reduction in total session cost.

## Key Takeaway

Prompt caching does not make per-turn costs decrease. It makes them **dramatically lower than they would otherwise be**. The savings are relative to the no-caching baseline, not to previous turns. As conversation history grows, per-turn cost will still rise — but the dominant cost component (system prompt + tools) is served at a 90% discount on every call.

## Related

- [ADR-012: Layered Cost Reduction](../architecture/decisions/ADR-012-layered-cost-reduction.md) — prompt caching is Layer 1
- [DESIGN-cost-metrics.md](../design/DESIGN-cost-metrics.md) — cost tracking architecture
- [Configuration: PromptCachingEnabled](config.md) — how to enable/disable
