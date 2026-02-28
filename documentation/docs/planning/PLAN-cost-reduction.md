# Plan: Agent Cost Reduction

## Status

**Phase 1 & 2 Completed** — Phases 1 (prompt caching, cheap compaction model) and 2 (tool result summarization, smart compaction trigger, concise output) implemented. Phase 3 (architecture) remains Planning.

**Prerequisite:** [Cost Metrics Logging](PLAN-cost-metrics-logging.md) — structured metrics infrastructure required to measure ROI of all levers below.

## Problem

The agent's primary running cost is LLM API spend (input + output tokens). Every turn sends the full conversation history, tool schemas, and system prompt as input tokens, then pays for output tokens. Costs compound across multi-step tasks with large tool results. We need a prioritised list of cost reduction levers, ordered by expected ROI.

## Cost Model Summary

Per-turn cost = `(input_tokens × input_price) + (output_tokens × output_price)`

With `claude-sonnet-4-5-20250929` at $3/$15 per MTok (input/output):
- A typical 3-round task hitting ~85K input tokens costs ~$0.26 in input alone per compaction cycle
- The compaction summarisation call itself adds ~$0.30-0.40 (100K input + 4K output)
- Output tokens at $15/MTok are 5x more expensive per token than input

---

## Prioritised Cost Levers

### Tier 1: High ROI, Low-Medium Effort

#### 1. Prompt Caching

**Impact:** Up to 90% reduction in input token cost for cached prefixes. This is the single highest-ROI lever available.

**Mechanism:** Anthropic prompt caching charges 10% of base price for cache hits on the stable prefix (system prompt + tool schemas + early conversation turns). Requires: (a) stable prefix content placed first, (b) explicit cache control headers, (c) minimum prefix length (1,024 tokens for Sonnet).

**Current state:** The system prompt is already compact and placed first — architecturally ready. Tool schemas are sent every turn unchanged — ideal for caching. But **no cache control headers are sent**. The `AnthropicProvider` does not use `cache_control` breakpoints.

**Existing research:**
- `deep-research-compaction.md` §Latency and token-cost economics — documents the 80-90% reduction claim
- `key-insights-and-takeaways.md` §3 — identifies tiered history as highest-ROI; prompt caching is the enabling mechanism
- `openclaw-research/` — documents auth-profile stickiness for preserving cache state

**Gaps:**
- No implementation plan for adding `cache_control` breakpoints to the Anthropic provider
- No measurement of current cache-eligible prefix size
- No analysis of whether MCP tool schemas are stable enough to include in the cached prefix
- Need to evaluate impact on `OpenAIProvider` (OpenAI has a different caching model — automatic, prefix-based, no explicit control)

---

#### 2. Cheaper Model for Compaction

**Impact:** 70-90% reduction in compaction call cost. Compaction is a summarisation task — does not need the full reasoning capability of the main model.

**Mechanism:** Use Haiku ($0.25/$1.25 per MTok) or a mini model for the compaction LLM call instead of Sonnet ($3/$15). The compaction call processes ~100K chars of formatted history and produces a 4K token summary — a straightforward task.

**Current state:** `ADR-010` explicitly identifies this as an architectural affordance: "using cheaper/faster models for compaction while using a more capable model for the main loop." The `CompactionStrategy` receives a `provider` parameter — adding a second provider for compaction is a small config change.

**Existing research:**
- `ADR-010` — documents the opportunity explicitly
- `DESIGN-compaction.md` — full algorithm spec; the compaction call is well-isolated

**Gaps:**
- No config schema for a separate compaction model/provider
- No quality evaluation: does Haiku produce sufficiently faithful summaries?
- No benchmark comparing Sonnet vs Haiku compaction output quality

---

#### 3. Tool Result Size Reduction

**Impact:** 30-60% reduction in per-turn input tokens for tool-heavy workflows. Tool results are the dominant cost driver in multi-step tasks (LinkedIn job details, Gmail bodies, web fetches can each be ~10K tokens).

**Mechanism:** Instead of injecting raw tool output (up to 40K chars), extract and return only the decision-relevant fields. For example: a LinkedIn job detail could return title/company/requirements as structured JSON (~500 tokens) instead of the full HTML-derived text (~2,500 tokens).

**Current state:** `_truncate_tool_result` does hard truncation at 40K chars but no semantic extraction. Tools return whatever they get from APIs.

**Existing research:**
- `key-insights-and-takeaways.md` §2 — "constrained action spaces beat open-ended ones"; SWE-agent's ACI showed 10.7pp improvement by constraining what tools return
- `DESIGN-compaction.md` — notes compaction previews tool results at 500+200 chars, implying full results are often wasteful
- `deep-research-compaction.md` §State compaction — discusses replacing large tool outputs with canonical structured records

**Gaps:**
- No per-tool analysis of actual token consumption (which tools are the most expensive?)
- No design for structured extraction vs raw passthrough per tool
- No measurement of how much tool result content the model actually uses vs ignores
- The `web_fetch` tool already does some extraction but other tools don't

---

#### 4. Smarter Compaction Trigger

**Impact:** 15-30% reduction in total session cost by avoiding premature or late compaction. Currently triggers at a fixed 80K estimated tokens — this may compact too early (wasting a summarisation call) or too late (accumulating unnecessary input cost on intervening turns).

**Mechanism:** (a) Use actual API-reported token counts instead of chars/4 heuristic. (b) Adaptive threshold based on task complexity. (c) Track cumulative input token spend and trigger compaction when the marginal cost of carrying history exceeds the cost of the compaction call.

**Current state:** `estimate_tokens()` uses `total_characters // 4`. The Anthropic provider already receives exact counts from `response.usage` but they're only logged, not fed back to the compaction decision.

**Existing research:**
- `DESIGN-compaction.md` — full algorithm spec with the 80K threshold
- `ADR-010` — acknowledges chars/4 as a limitation
- `deep-research-compaction.md` — discusses cost-optimal compaction timing

**Gaps:**
- No feedback loop from actual API usage to compaction trigger
- No analysis of optimal compaction threshold (what's the break-even point?)
- No tracking of cumulative session cost in real time

---

### Tier 2: Medium ROI, Medium Effort

#### 5. Model Selection / Downgrading for Simple Tasks

**Impact:** 50-80% cost reduction for tasks that don't need Sonnet's full capability. Many agent turns are simple (e.g., "read this file", "format this output") and could use Haiku.

**Mechanism:** Route simple turns to a cheaper model. Classification can be rule-based (turns following tool results with no complex reasoning needed) or LLM-based (a tiny classifier).

**Existing research:**
- `ADR-010` — multi-provider support enables this architecturally
- `openclaw-research/` — documents OpenClaw's model failover and tier selection
- `comparison-subagents-claude-code-vs-openclaw.md` — Claude Code uses Haiku for sub-agents

**Gaps:**
- No classification scheme for task complexity
- No design for per-turn model routing
- Risk of quality degradation needs evaluation
- No plan document exists

---

#### 6. Sub-Agent Architecture (Delegation to Cheaper Models)

**Impact:** 40-70% cost reduction for parallelisable sub-tasks. Instead of the main (expensive) model doing everything in one long context, delegate research/search tasks to cheaper sub-agents with isolated, smaller contexts.

**Mechanism:** Spawn Haiku-powered sub-agents for: file searches, web lookups, data extraction. Each sub-agent has a fresh, small context. Results are summarised back to the main agent.

**Existing research:**
- `claude-code-subagent-architecture.md` — detailed analysis of Claude Code's sub-agent model
- `comparison-subagents-claude-code-vs-openclaw.md` — four-way comparison of sub-agent patterns
- `openai-agents-sdk-multi-agent-deep-research.md` — handoff and agents-as-tools patterns
- `PLAN-openclaw-like-gateway-architecture.md` — planned gateway architecture could host sub-agents

**Gaps:**
- No sub-agent design for this project
- No plan for which tasks should be delegated
- Gateway architecture (prerequisite?) is still in planned state

---

#### 7. Tool Schema Optimisation

**Impact:** 5-15% reduction in per-turn input cost. Tool schemas are sent every turn as invisible but billable tokens. With 15+ built-in tools plus MCP tools, this is 2,000-5,000+ tokens per turn.

**Mechanism:** (a) Minimize tool description verbosity. (b) Only send schemas for tools relevant to the current task. (c) Group rarely-used tools behind a meta-tool. (d) Cache tool schemas as part of the prompt prefix (see lever #1).

**Existing research:**
- `key-insights-and-takeaways.md` §5 — notes "Cache MCP tool discovery results"
- `DESIGN-tool-system.md` — tool protocol and registry design
- SWE-agent ACI research — constrained action spaces

**Gaps:**
- No measurement of total tool schema token count
- No analysis of which tools are rarely used
- No design for dynamic tool selection per task
- No plan document exists

---

#### 8. Per-Turn Cost Tracking and Budgeting

**Impact:** Indirect but critical — enables informed decisions on all other levers. You can't optimise what you can't measure.

**Mechanism:** Surface per-turn and per-session cost in the REPL. Set session budgets with warnings/hard stops. Track cost by tool, by task type.

**Current state:** `anthropic_usage` tool queries the Admin API for org-level spend. Individual turn costs are logged at DEBUG level but not surfaced.

**Existing research:**
- `DESIGN-account-management-apis.md` — catalogs all usage/cost APIs
- The provider already receives `response.usage` — the data is available

**Plan:** [Cost Metrics Logging](PLAN-cost-metrics-logging.md) — covers structured metrics, provider-agnostic `UsageResult` abstraction, cost calculation, `metrics.jsonl` output, and session accumulators.

**Remaining gaps after metrics plan:**
- No per-turn cost display in REPL (metrics writes to file, not stdout)
- No session budget mechanism (warnings/hard stops at a spend threshold)
- These are features that build on top of the metrics infrastructure

---

### Tier 3: Lower ROI or Higher Effort

#### 9. Output Token Reduction

**Impact:** Variable. Output tokens are 5x more expensive than input ($15 vs $3 per MTok for Sonnet). Reducing verbosity directly cuts the most expensive token class.

**Mechanism:** (a) Tighten system prompt instructions for conciseness. (b) Set lower `MaxTokens` for turns that don't need long output. (c) Use structured output (JSON) to reduce prose overhead.

**Current state:** System prompt already says "Keep your responses concise." `MaxTokens` is 32,768 — generous for most turns.

**Existing research:**
- System prompt is documented in `system_prompt.py`
- `DESIGN-agent-loop.md` — loop design

**Gaps:**
- No measurement of actual output token usage distribution
- No per-turn adaptive MaxTokens
- No analysis of whether the model is being unnecessarily verbose

---

#### 10. Provider/Model Arbitrage

**Impact:** Potentially large but quality-dependent. OpenAI's GPT-4.1-mini is significantly cheaper than Sonnet for comparable quality on many tasks.

**Mechanism:** The multi-provider architecture already supports switching. Use the cheapest model that meets quality requirements for each task type.

**Current state:** `OpenAIProvider` is implemented and tested. Config-level model switching works.

**Existing research:**
- `ADR-010` — multi-provider support
- `openclaw-research/` — model failover patterns

**Gaps:**
- No quality benchmarking across providers for this agent's specific tasks
- No automatic failover implementation
- No cost comparison matrix
- No plan document exists

---

#### 11. MCP Tool Discovery Caching

**Impact:** Small per-session saving (eliminates repeated discovery calls). More important for latency than cost.

**Mechanism:** Cache the tool list from MCP servers for the session duration instead of rediscovering per-turn.

**Existing research:**
- `key-insights-and-takeaways.md` §5 — explicitly recommends this

**Gaps:**
- No investigation of current MCP discovery frequency
- No implementation plan

---

#### 12. Retry Cost Reduction

**Impact:** Small but prevents worst-case cost spikes. Currently retries up to 5 times with the full message payload on 429s.

**Mechanism:** (a) Respect `Retry-After` headers. (b) Consider compacting before retry if the context is large. (c) Cap total retry spend.

**Current state:** tenacity retry with exponential backoff (10s-320s), 5 attempts.

**Existing research:**
- `providers/common.py` — retry implementation
- `key-insights-and-takeaways.md` §8 — error recovery categories

**Gaps:**
- No analysis of retry frequency in production
- No cost-aware retry policy

---

## Summary Matrix

| # | Lever | Est. ROI | Effort | Existing Research | Plan Exists? |
|---|-------|----------|--------|-------------------|-------------|
| 1 | Prompt caching | **Very High** (up to 90% input) | Low | deep-research-compaction, key-insights | **No** |
| 2 | Cheap compaction model | **High** (70-90% compaction) | Low | ADR-010, DESIGN-compaction | **No** |
| 3 | Tool result size reduction | **High** (30-60% input) | Medium | key-insights §2, DESIGN-compaction | **No** |
| 4 | Smarter compaction trigger | **Medium** (15-30% session) | Medium | DESIGN-compaction, ADR-010 | **No** |
| 5 | Per-turn model routing | **Medium-High** (50-80% simple turns) | High | ADR-010, openclaw-research | **No** |
| 6 | Sub-agent delegation | **Medium-High** (40-70% sub-tasks) | High | 4 research docs, gateway plan | **Partial** (gateway plan) |
| 7 | Tool schema optimisation | **Low-Medium** (5-15% input) | Low | key-insights §5, DESIGN-tool-system | **No** |
| 8 | Cost tracking & budgeting | **Enabling** | Medium | DESIGN-account-mgmt-apis | **Yes** ([metrics plan](PLAN-cost-metrics-logging.md)) |
| 9 | Output token reduction | **Medium** (variable) | Low | system_prompt.py | **No** |
| 10 | Provider/model arbitrage | **Variable** | Medium | ADR-010, openclaw-research | **No** |
| 11 | MCP discovery caching | **Low** | Low | key-insights §5 | **No** |
| 12 | Retry cost reduction | **Low** (worst-case only) | Low | providers/common.py | **No** |

## Recommended Execution Order

**Phase 0 — Measurement (Lever 8):**
Implement [Cost Metrics Logging](PLAN-cost-metrics-logging.md) first. This is a prerequisite — without structured metrics, ROI of subsequent levers cannot be validated. Run for a few sessions to establish baseline cost data.

**Phase 1 — Quick wins (Levers 1, 2):**
Enable prompt caching, use Haiku for compaction. Both are low effort with immediate, measurable impact. Compare before/after metrics from Phase 0.

**Phase 2 — Structural improvements (Levers 3, 4, 9):**
Reduce tool result sizes, use real token counts for compaction triggers, tighten output verbosity. Requires per-tool analysis using `tool_execution` metrics from Phase 0.

**Phase 3 — Architecture (Levers 5, 6, 7):**
Per-turn model routing and sub-agent delegation. Higher effort but unlocks the largest long-term savings. Depends on gateway architecture. Note: compiled mode execution requires tools to return structured JSON instead of human-readable text — see [ADR-014](../architecture/decisions/ADR-014-mcp-unstructured-data-constraint.md).
