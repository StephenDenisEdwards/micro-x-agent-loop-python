# Cost Reduction Code Review

**Reviewed:** 2026-03-12
**Reviewer:** External analysis mapped against codebase
**Scope:** All cost reduction strategies applicable to a multi-provider LLM agent loop
**Status key:** `✅ Done` · `⚠️ Partial` · `🔲 Planned` · `❌ Gap`

---

## Review Context

This document maps a cost reduction strategy analysis against the current implementation and roadmap of micro-x-agent-loop-python. For each strategy, it records what is implemented, what is planned, what is missing, and what action (if any) has been taken since the review.

Primary reference plan: [`PLAN-cost-reduction.md`](../planning/PLAN-cost-reduction.md)
Research source: [`cost-reduction-research-report.md`](../research/cost-reduction-research-report.md)

---

## Strategy 1 — Prompt Caching

**Principle:** Cache the stable prefix (system prompt + tool schemas) so repeated turns pay 10% of input token cost rather than 100%.

| Attribute | Detail |
|-----------|--------|
| **Status** | ✅ Done |
| **Review finding** | Fully implemented. `cache_control: {"type": "ephemeral"}` applied to system prompt and tool schemas in `AnthropicProvider` when `PromptCachingEnabled=true`. OpenAI automatic prefix caching requires no explicit headers. |
| **Code location** | `src/micro_x_agent_loop/providers/anthropic_provider.py` lines 59–75 |
| **Config** | `PromptCachingEnabled` (default: `true`) |
| **Measured impact** | 82% savings for short sessions (4 calls); 26.6% for 8-call sessions as history grows beyond cached prefix. Source: `documentation/docs/operations/prompt-caching-cost-analysis.md` |
| **Residual gap** | Savings diminish as conversation history grows — caching alone is insufficient for long sessions. Other levers (compaction, output control) must pick up the slack. |
| **Manual test plan** | [MANUAL-TEST-prompt-caching.md](../testing/MANUAL-TEST-prompt-caching.md) |
| **Unit tests** | `tests/test_cost_reduction.py`: `PromptCachingConfigTests` (2 tests — default enabled, disabled via config), `PromptCachingProviderTests` (4 tests — stores flag, adds cache_control when enabled, no cache_control when disabled, no-tools edge case), `CreateProviderCachingTests` (2 tests — factory passes flag, factory default). `tests/test_usage.py`: `UsageResultTests.test_defaults`, `UsageResultTests.test_construction` (cache token fields), `EstimateCostTests.test_cache_tokens` (cache pricing). `tests/test_analyze_costs.py`: `AggregateTests.test_api_call_record` (cache token aggregation). `tests/providers/test_anthropic_provider.py`: `test_stream_chat_text_and_tool_use`, `test_stream_chat_text_only` (streaming with caching flag). |
| **Action taken** | — |

---

## Strategy 2 — Cheap Model for Compaction / Summarisation

**Principle:** Use a much cheaper model (Haiku at ~8% of Sonnet price) for summarisation tasks that don't need full reasoning capability.

| Attribute | Detail |
|-----------|--------|
| **Status** | ✅ Done |
| **Review finding** | Fully implemented. Compaction uses a separate `CompactionModel` provider instance. Default profile uses `claude-haiku-4-5-20251001` for compaction vs Sonnet for main loop. |
| **Code location** | `src/micro_x_agent_loop/bootstrap.py` lines 56–66; `src/micro_x_agent_loop/compaction.py` |
| **Config** | `CompactionStrategy: "summarize"`, `CompactionModel: "claude-haiku-4-5-20251001"`, `CompactionThresholdTokens: 80000` |
| **Estimated impact** | 70–90% reduction in compaction call cost (compaction call processes ~100K chars of history and outputs ~4K token summary). |
| **Residual gap** | No quality benchmark comparing Haiku vs Sonnet compaction faithfulness. Anecdotally working well but not formally evaluated. |
| **Manual test plan** | [MANUAL-TEST-compaction-model.md](../testing/MANUAL-TEST-compaction-model.md) |
| **Unit tests** | `tests/test_cost_reduction.py`: `CompactionModelConfigTests` (2 tests — default empty, custom model), `CompactionModelUsageTests.test_compaction_uses_specified_model` (verifies cheap model is used for summarisation). `tests/test_compaction_strategy.py`: `test_summarize_calls_provider_create_message` (compaction invokes provider), `test_compaction_callback_invoked` (callback with usage). `tests/test_metrics.py`: `BuildCompactionMetricTests.test_structure`, `SessionAccumulatorTests.test_add_compaction` (compaction cost tracking). |
| **Action taken** | — |

---

## Strategy 3 — Conversation History Summarisation (Compaction)

**Principle:** Instead of replaying full history on every turn, periodically summarise old context and replace it with a compact summary.

| Attribute | Detail |
|-----------|--------|
| **Status** | ✅ Done |
| **Review finding** | Fully implemented. `SummarizeCompactionStrategy` compacts when estimated tokens exceed threshold. Smart trigger uses actual API-reported token counts (not char/4 heuristic) when `SmartCompactionTriggerEnabled=true`. |
| **Code location** | `src/micro_x_agent_loop/compaction.py`; `src/micro_x_agent_loop/agent.py` lines 308–311 |
| **Config** | `CompactionStrategy`, `CompactionThresholdTokens`, `SmartCompactionTriggerEnabled` (default: `true`) |
| **Estimated impact** | Prevents unbounded input token growth across long sessions. Smart trigger corrects 10–20% estimation errors from char-based counting. |
| **Residual gap** | No cost-optimal threshold analysis — break-even between carrying history cost vs compaction call cost not formally modelled. |
| **Manual test plan** | [MANUAL-TEST-compaction-strategy.md](../testing/MANUAL-TEST-compaction-strategy.md) |
| **Unit tests** | `tests/test_compaction_strategy.py`: `test_maybe_compact_returns_original_below_threshold`, `test_maybe_compact_summarizes_when_over_threshold`, `test_maybe_compact_falls_back_on_summary_error`, `test_compaction_callback_invoked`, `test_format_for_summarization_includes_tool_blocks`. `tests/test_compaction_and_llm_utils.py`: `EstimateTokensExtraTests` (3 tests — token counting), `FormatForSummarizationTests` (6 tests — message formatting), `AdjustBoundaryExtraTests` (4 tests — tool_use/result pair protection), `RebuildMessagesListContentTests` (2 tests — role alternation). `tests/test_cost_reduction.py`: `SmartCompactionConfigTests` (2 tests — default enabled, disabled), `SmartCompactionTriggerTests` (3 tests — actual tokens, fallback to estimate). |
| **Action taken** | — |

---

## Strategy 4 — Per-Turn Cost Tracking and Visibility

**Principle:** You can't optimise what you can't measure. Surface cost data to users and enable budget enforcement.

| Attribute | Detail |
|-----------|--------|
| **Status** | ✅ Done |
| **Review finding** | **Tracking: Done.** Comprehensive structured metrics. **Visibility: Done.** CLI status bar shows per-turn cost/tokens. **Budget enforcement: Done.** `SessionBudgetUSD` with warn at 80%, hard stop at 100%. |
| **Code location** | `src/micro_x_agent_loop/metrics.py`; `src/micro_x_agent_loop/usage.py`; `src/micro_x_agent_loop/agent.py` |
| **Plan** | [`PLAN-cost-metrics-logging.md`](../planning/PLAN-cost-metrics-logging.md) — completed. [`PLAN-cli-status-bar.md`](../planning/PLAN-cli-status-bar.md) — completed. |
| **Residual gaps** | None — all three components (tracking, visibility, budget enforcement) implemented. |
| **Action taken** | CLI status bar completed. `SessionBudgetUSD` with warn/stop implemented (2026-03-12). Status bar shows budget percentage when set. |

---

## Strategy 5 — Tool Result Size Reduction

**Principle:** Tool results (web fetches, file reads, API responses) are the dominant per-turn input cost driver in tool-heavy workflows. Return only decision-relevant content.

| Attribute | Detail |
|-----------|--------|
| **Status** | ⚠️ Partial |
| **Review finding** | **Hard truncation: Done.** `_truncate_tool_result` caps at `MaxToolResultChars: 40000`. **Structured data pipeline: Done.** `ToolResult.structured` + `ToolResultFormatter` with per-tool config (json/table/text/key_value). **Summarisation: Implemented but deprecated.** `ToolResultSummarizationEnabled` (default: `false`) — ADR-013 documents that lossy summarisation drops data the main model needs. |
| **Code location** | `src/micro_x_agent_loop/turn_engine.py`; `src/micro_x_agent_loop/tool_result_formatter.py` |
| **Config** | `MaxToolResultChars: 40000`, `ToolResultSummarizationEnabled: false`, `ToolFormatting` (per-tool format config) |
| **ADR** | [ADR-013](../architecture/decisions/) — tool result summarisation unreliable. [ADR-014](../architecture/decisions/ADR-014-mcp-unstructured-data-constraint.md) — accepted (Option C), structured results now available. |
| **Residual gaps** | Per-tool extraction is now possible via `ToolResult.structured` and `ToolResultFormatter`. Remaining: not all MCP servers may populate `structuredContent` — tuning per-tool formatting config for optimal token reduction. |
| **Action taken** | ADR-014 accepted (2026-03-12). Structured data pipeline (`ToolResult.structured`, `McpToolProxy` `structuredContent` extraction, `ToolResultFormatter`) already implemented. |

---

## Strategy 6 — Tool Result Data Format (Structured vs Unstructured)

**Principle:** If tool results are structured (JSON), the agent can reliably extract fields. This unblocks both semantic extraction and compiled mode execution.

| Attribute | Detail |
|-----------|--------|
| **Status** | ✅ Done |
| **Review finding** | ADR-014 accepted (Option C). The codebase has implemented structured tool results incrementally: `ToolResult` dataclass carries both `text` and `structured` fields, `McpToolProxy` preserves `structuredContent` from MCP responses, and `ToolResultFormatter` provides config-driven per-tool formatting (json/table/text/key_value). All tools are now TypeScript MCP servers — no Python built-in tools remain. |
| **ADR** | [ADR-014](../architecture/decisions/ADR-014-mcp-unstructured-data-constraint.md) — accepted (v3, 2026-03-12) |
| **Code location** | `src/micro_x_agent_loop/tool.py` (`ToolResult`); `src/micro_x_agent_loop/mcp/mcp_tool_proxy.py` (`structuredContent`); `src/micro_x_agent_loop/tool_result_formatter.py` |
| **Residual gaps** | LLM extraction fallback (Option B) for third-party MCP servers not implemented — not needed yet as all production tools are our own. |
| **Action taken** | ADR-014 accepted as Option C (2026-03-12). Implementation already in place. No longer blocks strategies 5 or 11. |

---

## Strategy 7 — Sub-Agent Delegation to Cheaper Models

**Principle:** Delegate parallelisable sub-tasks (file search, web lookup, data extraction) to cheap sub-agents with fresh, small contexts instead of doing everything in the main expensive context.

| Attribute | Detail |
|-----------|--------|
| **Status** | ✅ Done |
| **Review finding** | Architecture fully implemented: `SubAgentRunner`, `spawn_subagent` pseudo-tool, configurable sub-agent model and limits. Now enabled by default with comprehensive routing directive. |
| **Code location** | `src/micro_x_agent_loop/sub_agent.py`; `src/micro_x_agent_loop/agent.py` lines 94–108; `src/micro_x_agent_loop/system_prompt.py` (`_SUBAGENT_DIRECTIVE`) |
| **Config** | `SubAgentsEnabled: true`, `SubAgentModel`, `SubAgentTimeout: 120`, `SubAgentMaxTurns: 15`, `SubAgentMaxTokens: 4096` |
| **Estimated impact** | 40–70% cost reduction for delegated sub-tasks. |
| **Residual gaps** | Observability (metrics aggregation, memory tracking) not yet implemented (Phase 2b). No formal evaluation of delegation quality with real usage data. |
| **Action taken** | Enabled by default in `config-base.json`. `_SUBAGENT_DIRECTIVE` rewritten with explicit routing policy, cost motivation, DELEGATE/DO NOT rules, and concrete examples (2026-03-12). |

---

## Strategy 8 — Per-Turn Model Routing

**Principle:** Route simple turns (formatting, reading a file, extracting a field) to a cheap model rather than using Sonnet for every call.

| Attribute | Detail |
|-----------|--------|
| **Status** | ✅ Done |
| **Review finding** | Per-turn model routing implemented via heuristic classifier (`turn_classifier.py`). Routes tool-result continuations, short conversational messages, and short follow-ups to a cheap model. Complexity keywords guard ensures complex turns stay on the main model. Opt-in via `PerTurnRoutingEnabled`. |
| **Code location** | `src/micro_x_agent_loop/turn_classifier.py`; `src/micro_x_agent_loop/turn_engine.py`; `src/micro_x_agent_loop/agent.py` |
| **Config** | `PerTurnRoutingEnabled: false`, `PerTurnRoutingModel`, `PerTurnRoutingProvider`, `PerTurnRoutingMaxUserChars: 200`, `PerTurnRoutingShortFollowupChars: 50`, `PerTurnRoutingComplexityKeywords` |
| **Estimated impact** | 50–80% cost reduction for turns that don't need Sonnet capability. |
| **Residual gaps** | Quality evaluation with real usage data not yet done. Classifier is conservative (errs toward main model). No automatic fallback if cheap model produces poor results. |
| **Action taken** | Implemented (2026-03-12). `Stage2Model` → Haiku. Per-turn routing with heuristic classifier. |

---

## Strategy 9 — Output Token Reduction

**Principle:** Output tokens are 5× more expensive than input ($15 vs $3 per MTok for Sonnet). Reducing verbosity directly cuts the most expensive token class.

| Attribute | Detail |
|-----------|--------|
| **Status** | ⚠️ Partial |
| **Review finding** | `ConciseOutputEnabled` config appends a system directive to minimise output tokens. Disabled by default. No per-turn adaptive `MaxTokens`. No measurement of actual output token distribution to know if the model is being unnecessarily verbose. |
| **Code location** | `src/micro_x_agent_loop/system_prompt.py` |
| **Config** | `ConciseOutputEnabled: true`, `MaxTokens: 32768` |
| **Residual gaps** | No data on whether the model over-produces output. `MaxTokens: 32768` is generous — many turns need far fewer. |
| **Action taken** | Enabled in `config-base.json` (was already `true` at time of review). |

---

## Strategy 10 — On-Demand Tool Discovery (Schema Token Reduction)

**Principle:** For large tool sets, don't send all tool schemas every turn. Let the model request only the tools it needs via a discovery pseudo-tool.

| Attribute | Detail |
|-----------|--------|
| **Status** | ⚠️ Partial → ✅ Done (provider-aware) |
| **Review finding** | Fully implemented: `tool_search` pseudo-tool with on-demand discovery, triggers at >50 tools. Now **provider-aware** (`ToolSearchEnabled: "auto"`): Anthropic auto-disables tool search to preserve cache; OpenAI uses token-threshold heuristic. Both providers use **canonical tool serialisation** for byte-stable cache prefixes. Static tool groups (lane routing) shelved — marginal savings don't justify config complexity. |
| **Code location** | `src/micro_x_agent_loop/tool_search.py`; `src/micro_x_agent_loop/tool.py` (`canonicalise_tools`) |
| **Config** | `ToolSearchEnabled: "auto"` (options: `"auto"`, `"true"`, `"false"`) |
| **Research** | [`kv-cache-and-mcp-tool-routing.md`](../research/kv-cache-and-mcp-tool-routing.md) — full cost modelling. Key insight: Anthropic's 90% cache discount makes full-set schema caching cheap (~$0.001/turn); OpenAI's 50–75% discount makes routing worthwhile even at ~60 tools. |
| **Residual gaps** | Static tool groups (lane routing) shelved. Vector-DB semantic routing not implemented (not needed at current scale). |
| **Action taken** | Provider-aware `should_activate_tool_search()` + canonical tool serialisation implemented (2026-03-12). `config-base.json` changed to `"auto"`. |

---

## Strategy 11 — Compiled Mode / Batch Execution

**Principle:** For structured, repeatable tasks (batch scoring, data extraction pipelines), compile prompts to deterministic code rather than running full LLM inference for every item.

| Attribute | Detail |
|-----------|--------|
| **Status** | 🔲 Planned (Phase 4+) |
| **Review finding** | Stage 1 (pattern matching) and Stage 2 (LLM classification) both detect batch/scoring/structured-output signals. Detection is diagnostic only — no compiled execution path exists. Mode analysis is disabled by default (`ModeAnalysisEnabled: false`). |
| **Code location** | `src/micro_x_agent_loop/mode_selector.py` |
| **Config** | `ModeAnalysisEnabled: false`, `Stage2ClassificationEnabled: true` |
| **Blockers** | ~~ADR-014 (tool data format decision)~~ — resolved (2026-03-12). Structured tool outputs now available via `ToolResult.structured`. Remaining blocker: no execution path or plan document for compiled mode. |
| **Residual gaps** | No execution path. No plan document for compiled mode beyond detection. Significant architectural work required. |
| **Action taken** | ADR-014 blocker resolved (2026-03-12). |

---

## Strategy 12 — Batch API for Autonomous Jobs

**Principle:** The Anthropic Batch API charges 50% of standard pricing for asynchronous requests. Scheduled `--run` jobs (broker mode) were assumed to be natural candidates.

| Attribute | Detail |
|-----------|--------|
| **Status** | ❌ Dropped |
| **Review finding** | **Architecturally incompatible.** Batch API submits a single LLM request and returns one response asynchronously — it cannot participate in multi-turn agentic loops. Broker `--run` jobs execute full agent loops (LLM → tool execution → feed results → LLM → repeat), requiring tool results from turn N to construct turn N+1. Chaining batch submissions between tool calls would turn a 6-second job into a multi-hour job with high complexity for modest savings. |
| **Code location** | `src/micro_x_agent_loop/broker/` |
| **Residual gaps** | None — dropped as infeasible. |
| **Action taken** | Dropped (2026-03-12). Batch API is incompatible with agentic execution. Cost reduction for broker jobs served by existing levers (prompt caching, per-turn routing, sub-agent delegation). |

---

## Strategy 13 — Provider and Model Arbitrage

**Principle:** Use the cheapest provider that meets quality requirements for each task type. Pricing differences across providers are significant (DeepSeek-chat: $0.07/M cached input; GPT-4.1-mini: $0.10/M cached; Haiku 4.5 batch: $0.05/M input).

| Attribute | Detail |
|-----------|--------|
| **Status** | ⚠️ Partial |
| **Review finding** | `OpenAIProvider` fully implemented. Multi-provider factory (ADR-010) supports config-level switching. No runtime arbitrage — provider is static per session. No quality benchmarking for this agent's tasks across providers. No DeepSeek or Gemini provider. |
| **Code location** | `src/micro_x_agent_loop/providers/openai_provider.py`; `src/micro_x_agent_loop/provider.py` |
| **Residual gaps** | (a) No automatic failover. (b) No cost comparison matrix for agent-specific tasks. (c) No additional provider implementations (DeepSeek, Gemini). (d) Per-turn model routing (Strategy 8) is a prerequisite for meaningful arbitrage. |
| **Action taken** | — |

---

## Strategy 14 — Retry Cost Reduction

**Principle:** On rate limit (429) retries, avoid re-sending unnecessarily large payloads. Cap total retry spend.

| Attribute | Detail |
|-----------|--------|
| **Status** | ❌ Gap |
| **Review finding** | Tenacity retry with exponential backoff (10s–320s, 5 attempts) is implemented. No `Retry-After` header respect. No pre-retry compaction. No retry spend cap. |
| **Code location** | `src/micro_x_agent_loop/providers/common.py` |
| **Residual gaps** | Low priority — retry frequency in practice is unknown. Primarily a worst-case protection concern rather than a routine cost lever. |
| **Action taken** | — |

---

## Summary

| # | Strategy | Status | Priority | Action Taken |
|---|----------|--------|----------|--------------|
| 1 | Prompt caching | ✅ Done | — | — |
| 2 | Cheap model for compaction | ✅ Done | — | — |
| 3 | Conversation history summarisation | ✅ Done | — | — |
| 4 | Cost tracking and visibility | ✅ Done | Tracking, CLI visibility, and budget caps all implemented | Session budget caps (2026-03-12) |
| 5 | Tool result size reduction | ⚠️ Partial | Medium — structured pipeline in place; per-tool formatting tuning remains | ADR-014 resolved (2026-03-12) |
| 6 | Tool result data format (ADR-014) | ✅ Done | — | Option C accepted, implemented incrementally (2026-03-12) |
| 7 | Sub-agent delegation | ✅ Done | Enabled by default, routing directive with examples | Routing policy + enabled (2026-03-12) |
| 8 | Per-turn model routing | ✅ Done | Heuristic classifier, opt-in, conservative defaults | Implemented (2026-03-12) |
| 9 | Output token reduction | ✅ Done | Low — `ConciseOutputEnabled` enabled in config-base.json | Enabled |
| 10 | On-demand tool discovery | ✅ Done | Provider-aware auto + canonical serialisation | Implemented (2026-03-12) |
| 11 | Compiled mode / batch execution | 🔲 Planned | Low — Phase 4+, ADR-014 blocker resolved | ADR-014 resolved (2026-03-12) |
| 12 | Batch API for broker jobs | ❌ Dropped | — | Dropped (2026-03-12) — incompatible with multi-turn agentic loops |
| 13 | Provider and model arbitrage | ⚠️ Partial | Low — OpenAI exists; no benchmarking or auto-switching | — |
| 14 | Retry cost reduction | ❌ Gap | Low — worst-case only, low practical impact | — |

### Top Unaddressed Opportunities

1. ~~**Per-turn cost display in REPL**~~ — ✅ Done ([CLI Status Bar](../planning/PLAN-cli-status-bar.md)).
2. ~~**Session budget caps**~~ — ✅ Done (2026-03-12). `SessionBudgetUSD` with warn at 80%, hard stop at 100%.
3. ~~**ADR-014 decision**~~ — ✅ Done (2026-03-12). Option C accepted; structured tool results implemented (`ToolResult.structured`, `ToolResultFormatter`). Strategies 5 and 11 unblocked.
4. ~~**Per-turn model routing**~~ — ✅ Done (2026-03-12). Heuristic classifier routes tool-result continuations and short messages to cheap model.
5. ~~**Batch API for broker**~~ — Dropped (2026-03-12). Incompatible with multi-turn agentic loops.
6. ~~**`Stage2Model` → Haiku**~~ — ✅ Done (2026-03-12). Changed to `claude-haiku-4-5-20251001` in `config-base.json`.
