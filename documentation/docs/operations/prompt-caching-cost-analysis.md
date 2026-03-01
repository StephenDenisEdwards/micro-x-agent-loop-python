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

## Longer Session: 8-Call Analysis

The short session above is best-case for caching — the cached tokens (12,692) dwarf the conversation history. In a longer, more realistic session, the balance shifts. The following data comes from an 8-call job-search session logged to `api_payloads.jsonl`.

### API Payload Log

```
Call 1:  Messages=1   Stop=tool_use  in=1,796   out=142    cache_rd=0       cache_wr=12,692  Cost=$0.018371
Call 2:  Messages=3   Stop=tool_use  in=11,580  out=271    cache_rd=12,692  cache_wr=0       Cost=$0.014204
Call 3:  Messages=5   Stop=tool_use  in=13,375  out=340    cache_rd=12,692  cache_wr=0       Cost=$0.016344
Call 4:  Messages=7   Stop=tool_use  in=15,661  out=320    cache_rd=12,692  cache_wr=0       Cost=$0.018530
Call 5:  Messages=9   Stop=tool_use  in=18,694  out=338    cache_rd=12,692  cache_wr=0       Cost=$0.021653
Call 6:  Messages=11  Stop=tool_use  in=22,396  out=307    cache_rd=12,692  cache_wr=0       Cost=$0.025200
Call 7:  Messages=13  Stop=tool_use  in=25,015  out=7,206  cache_rd=12,692  cache_wr=0       Cost=$0.062314
Call 8:  Messages=15  Stop=end_turn  in=32,275  out=402    cache_rd=12,692  cache_wr=0       Cost=$0.035554
```

### Session Totals

| Metric | Value |
|--------|-------|
| Total API calls | 8 |
| Fresh input tokens | 140,792 (58.1%) |
| Cache-read tokens | 88,844 (36.7%) |
| Cache-create tokens | 12,692 (5.2%) |
| Output tokens | 9,326 |
| **Total cost (with caching)** | **$0.212** |
| **Total cost (without caching)** | **$0.289** |
| **Savings** | **$0.077 (26.6%)** |

### Observations

1. **Cache write on Call 1** — The first call pays $0.016 for cache creation (12,692 × $1.25/MTok) with no cache reads. This one-time cost pays for itself by Call 2.

2. **Diminishing caching returns** — Savings drop from 82% (short session) to 26.6% here. As conversation history grows, fresh input tokens dominate and the fixed-size cached portion becomes a smaller fraction of total input.

3. **Cost progression** — Costs rise steadily from $0.014 to $0.036 as conversation history accumulates (1,796 → 32,275 input tokens), interrupted by one output spike.

4. **Output spike on Call 7** — A 7,206-token output (vs. ~300 typical) cost $0.062, more than Calls 2–5 combined. Output tokens are expensive ($5.00/MTok for Haiku) and not subject to caching.

### Token Composition Over Time

```
Call 1:  [====] in=1.8K                          cache_rd=0     cache_wr=12.7K
Call 2:  [============] in=11.6K                  cache_rd=12.7K
Call 3:  [==============] in=13.4K                cache_rd=12.7K
Call 4:  [================] in=15.7K              cache_rd=12.7K
Call 5:  [===================] in=18.7K           cache_rd=12.7K
Call 6:  [======================] in=22.4K        cache_rd=12.7K
Call 7:  [=========================] in=25.0K     cache_rd=12.7K  out=7.2K !!
Call 8:  [================================] in=32.3K  cache_rd=12.7K
```

The cached portion (12.7K) stays constant while fresh input grows from 1.8K to 32.3K — a 18× increase. By Call 8, cached tokens are only 28% of total input.

## Key Takeaways

1. **Prompt caching does not make per-turn costs decrease.** It makes them dramatically lower than they would otherwise be. The savings are relative to the no-caching baseline, not to previous turns.

2. **Caching has diminishing returns in longer sessions.** When conversation history is small (short sessions), caching the system prompt + tools saves ~80%. As history grows, savings shrink because the cached portion becomes a smaller fraction of total input.

3. **For longer sessions, other cost levers matter more:**
   - **Compaction** — reducing conversation history size has more impact than caching when history dominates input
   - **Output control** — a single verbose response can cost more than several normal turns (Call 7 above)
   - **Cheaper models** — Haiku 4.5 is already the cheapest option; model choice is the largest single lever

4. **Cache creation has a cost.** The first call pays a write premium ($1.25/MTok vs. $1.00/MTok input). For very short sessions (1–2 calls), caching can actually cost slightly more than not caching.

## API vs. Chat Subscription: When Does the API Make Sense?

The per-token costs above are specific to the **Anthropic API**. Claude Chat (claude.ai) uses a flat subscription model with no per-token charges. This raises a natural question: is the API massively more expensive for the same work?

### Cost Comparison

| | Anthropic API | Claude Chat Pro | Claude Chat Max |
|---|---|---|---|
| Pricing | Per-token | $20/month flat | $100/month flat |
| Models available | All (choose per call) | Sonnet, Opus | Sonnet, Opus |
| Rate limits | None (pay for what you use) | Usage caps | Higher caps |

**Break-even analysis for the 8-call session above ($0.21 on Haiku 4.5):**

- vs. Pro ($20/mo): ~95 similar sessions/month before API exceeds subscription cost
- vs. Max ($100/mo): ~476 similar sessions/month

**But model choice changes the equation dramatically.** The session above used Haiku 4.5 ($1.00/$5.00 per MTok). The same session on other models:

| Model | Estimated session cost | Sessions to exceed Pro ($20/mo) |
|-------|----------------------|-------------------------------|
| Haiku 4.5 | ~$0.21 | ~95 |
| Sonnet 4.6 | ~$0.64 | ~31 |
| Opus 4.6 | ~$1.06 | ~19 |

Chat Pro includes Sonnet and Opus at no extra per-token cost, so for interactive conversational use, the subscription is almost always cheaper.

### When the API Is Worth It

The API's per-token cost is justified when you need capabilities Chat doesn't offer:

- **Custom tools** — this project uses 59 MCP tools (filesystem, web search, etc.)
- **Custom system prompts** — tailored instructions, user memory, dynamic context
- **Programmatic control** — automated workflows, agent loops, batch processing
- **Prompt caching** — reduces costs for repeated system prompts across calls
- **Structured cost tracking** — per-call metrics, session budgets, cost analysis
- **Model flexibility** — use Haiku for simple tasks, Opus for complex ones, per call

**Bottom line:** For casual interactive use, Chat subscriptions are far cheaper. The API makes economic sense when you need automation, custom tooling, or are building a product — things Chat cannot do.

## Related

- [ADR-012: Layered Cost Reduction](../architecture/decisions/ADR-012-layered-cost-reduction.md) — prompt caching is Layer 1
- [DESIGN-cost-metrics.md](../design/DESIGN-cost-metrics.md) — cost tracking architecture
- [Configuration: PromptCachingEnabled](config.md) — how to enable/disable
