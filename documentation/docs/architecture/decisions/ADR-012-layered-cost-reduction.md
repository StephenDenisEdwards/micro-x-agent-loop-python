# ADR-012: Layered Cost Reduction Architecture

## Status

Accepted

## Context

API cost is the dominant operational expense. Every agent turn sends the full conversation history, tool schemas, and system prompt as input tokens, then pays for output tokens. With Sonnet at $3/$15 per MTok (input/output), a typical 10-turn session costs $2.00-2.50. Costs compound in multi-step workflows with large tool results and repeated compaction cycles.

The [Cost Metrics Logging](../../design/DESIGN-cost-metrics.md) infrastructure (Phase 0) established structured per-turn cost measurement. With baseline data available, the question became: what is the best architecture for reducing cost without degrading agent quality?

Options considered for the overall approach:

1. **Model downgrade** — switch from Sonnet to a cheaper model for all interactions. Simple but reduces quality across the board.
2. **External proxy / gateway** — route requests through a cost-optimizing proxy (caching, model routing, compression). Adds infrastructure complexity and a network hop.
3. **Layered, config-driven optimizations within the agent** — implement multiple independent cost levers at different points in the request lifecycle, each configurable and opt-in, using the existing provider abstraction for secondary model calls.

## Decision

Adopt option 3: a layered architecture with five independent cost reduction features, each targeting a different cost driver, all configurable via `config.json` with sensible defaults.

Reasons:

- **Composable.** Each feature operates independently at a different point in the lifecycle (API request construction, tool result processing, compaction triggering, system prompt, response generation). They can be enabled in any combination.
- **No quality regression by default.** Features with no quality tradeoff (prompt caching, smart compaction trigger) are on by default. Features that trade fidelity for cost (tool summarization, concise output) are off by default.
- **Existing abstractions suffice.** The provider factory (ADR-010) already supports creating multiple provider instances for different models. No new abstractions or infrastructure needed.
- **Measurable.** Each feature's impact is observable through the existing metrics pipeline — cache hit rates, compaction timing, summarization counts, output token volumes.

### The Five Layers

#### Layer 1: Prompt Caching (provider-level)

**Cost driver:** System prompt and tool schemas (~5-10K tokens) are re-sent identically on every turn.

**Mechanism:** Tag the system prompt and the last tool schema with Anthropic `cache_control: {"type": "ephemeral"}` breakpoints. Subsequent turns read from cache at 10% of the input token price.

**Implementation:** `AnthropicProvider` constructor accepts `prompt_caching_enabled`. When enabled, `stream_chat()` wraps the system parameter as a list with cache control and adds cache control to the last tool. Only affects the streaming chat path — `create_message()` (used for compaction/summarization) has no system prompt or tools, so caching is irrelevant there. OpenAI does automatic prefix caching with no explicit headers, so `OpenAIProvider` is unchanged.

**Config:** `PromptCachingEnabled` (default: `true`)

#### Layer 2: Cheaper Compaction Model (compaction-level)

**Cost driver:** Compaction summarization uses the main model ($3/$15 per MTok for Sonnet) for a straightforward summarization task.

**Mechanism:** Route compaction calls to a cheaper model (Haiku at $0.25/$1.25 per MTok). The compaction strategy already accepts a `model` parameter — this is purely a config-level change.

**Implementation:** `bootstrap.py` passes `app.compaction_model or app.model` to `SummarizeCompactionStrategy`. The compaction provider instance is separate from the main provider (established pattern from ADR-010).

**Config:** `CompactionModel` (default: `""` = use main model)

#### Layer 3: Tool Result Summarization (tool result pipeline)

**Cost driver:** Large tool results (5-40K chars from web fetches, file reads, MCP tools) are carried verbatim in conversation history across all subsequent turns.

**Mechanism:** After truncation, if a tool result exceeds a character threshold, call a cheap model to summarize it before it enters conversation history. The summary preserves decision-relevant data (names, numbers, IDs, paths, errors) while discarding raw bulk.

**Alternatives considered for this layer:**

1. **Per-tool structured extraction** — each tool returns a summary alongside raw output. Rejected: requires modifying every tool and designing per-tool schemas.
2. **Middleware / post-processor** — separate pipeline stage. Rejected: introduces a new abstraction for a single transform.
3. **Summarization in TurnEngine** — after truncation, call a cheap model. **Chosen:** natural extension of existing pipeline, tool-agnostic, graceful fallback.
4. **Compaction-only** — rely on compaction to shrink results later. Rejected: full results sit in history for multiple turns before compaction fires.

**Implementation:** TurnEngine gets `_summarize_tool_result()` called after `_truncate_tool_result()`. Uses a second provider instance (`summarization_provider`) with its own model via `create_message()` (non-streaming). If summarization fails, the original truncated result is used. A `was_summarized` field in tool execution metrics provides observability.

The summarization provider is a separate `LLMProvider` instance because: (a) the main provider may have prompt caching enabled and summarization calls should not interfere with cache state, (b) the model is typically different (Haiku vs Sonnet), (c) the `create_provider()` factory is reused with no new code.

**Config:** `ToolResultSummarizationEnabled` (default: `false`), `ToolResultSummarizationModel` (default: `""` = main model), `ToolResultSummarizationThreshold` (default: `4000` chars)

#### Layer 4: Smart Compaction Trigger (compaction control loop)

**Cost driver:** The tiktoken-based token estimate used for compaction triggering can be 10-20% off (wrong encoding for Claude, doesn't account for system prompt/tool schema overhead). This causes compaction to fire too early (wasting a summarization call) or too late (accumulating unnecessary input cost on intervening turns).

**Mechanism:** Feed actual API-reported `input_tokens` from `response.usage` back to the compaction strategy. When available, use the actual count instead of the tiktoken estimate for threshold comparison.

**Implementation:** `SummarizeCompactionStrategy` gains `update_actual_tokens(input_tokens)` and `smart_trigger_enabled`. `Agent.on_api_call_completed()` feeds actual tokens on every main API call. On the first turn (before any API response), falls back to the tiktoken estimate.

**Config:** `SmartCompactionTriggerEnabled` (default: `true`)

#### Layer 5: Concise Output Mode (system prompt)

**Cost driver:** Output tokens are 5x more expensive than input ($15 vs $3 per MTok for Sonnet). The model's default conversational style includes pleasantries, redundant explanations, and echoed data.

**Mechanism:** Append a directive to the system prompt: minimize output tokens, use bullet points, omit filler, target 200 words per response.

**Implementation:** `get_system_prompt()` accepts `concise_output_enabled` and appends the directive when enabled.

**Config:** `ConciseOutputEnabled` (default: `false`)

### Architectural Pattern: Secondary Provider Instances

A recurring pattern across layers 2 and 3 is the use of secondary `LLMProvider` instances for cheaper models. This is enabled by the provider factory from ADR-010:

- **Compaction** uses its own provider instance with `CompactionModel` (Haiku)
- **Tool summarization** uses its own provider instance with `ToolResultSummarizationModel` (Haiku)
- Both call `create_message()` (non-streaming) — they don't need the streaming/spinner infrastructure

Each instance is independent: separate API client, separate retry state, no shared mutable state with the main provider. The cost of creating multiple `AsyncAnthropic` client instances is negligible.

## Consequences

**Easier:**

- Reducing session cost by 40-50% with no code changes — just config
- Measuring the impact of each feature independently via metrics
- Adding future cost levers (per-turn model routing, sub-agent delegation) as additional layers without modifying existing ones
- A/B testing cost configurations by comparing metrics across sessions

**Harder:**

- Debugging requires understanding which layers are active and how they interact. A tool result may be truncated, then summarized, with the summary entering a conversation that later gets compacted — three transformations deep. Metrics and logging at each stage mitigate this.
- The total number of config fields for cost management (7 new fields) increases configuration surface area. Sensible defaults mean most users need not touch them.

**Risks:**

- **Information loss in summarization.** The summarization model may drop data the main model would have used. Mitigated by: opt-in default, preservation-focused prompt, configurable threshold, `was_summarized` metric for monitoring. **Update: this risk materialised in practice — see [ADR-013](ADR-013-tool-result-summarization-reliability.md).** Tool result summarization is fundamentally unreliable for information-dense, unstructured results (web searches, email, documents) and is no longer recommended for general-purpose use.
- **Cost break-even for summarization.** If tool results are rarely above threshold, summarization calls add cost without savings. The 4,000-char default ensures only genuinely large results are summarized.
- **Prompt caching invalidation.** Any change to system prompt text or tool schemas invalidates the cache. Features that modify the system prompt (concise output, user memory) should be set once per session, not toggled mid-conversation.

**Related:**

- [ADR-014](ADR-014-mcp-unstructured-data-constraint.md) — accepted (Option C, 2026-03-12). Tools now return structured data via `ToolResult.structured` and `McpToolProxy` preserves `structuredContent`. `ToolResultFormatter` provides config-driven per-tool formatting. This unblocks Layer 3 structured extraction and compiled mode.

**Future layers (Phase 3):**

- Per-turn model routing — route simple turns to Haiku
- Sub-agent delegation — spawn cheaper sub-agents for research tasks
- Tool schema optimization — reduce per-turn schema token overhead
