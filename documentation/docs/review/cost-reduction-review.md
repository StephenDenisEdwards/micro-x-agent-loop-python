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
| **Action taken** | — |

---

## Strategy 4 — Per-Turn Cost Tracking and Visibility

**Principle:** You can't optimise what you can't measure. Surface cost data to users and enable budget enforcement.

| Attribute | Detail |
|-----------|--------|
| **Status** | ⚠️ Partial |
| **Review finding** | **Tracking: Done.** Comprehensive structured metrics: per-call, per-tool, per-compaction, per-session. `SessionAccumulator` in `metrics.py`. Cache-aware cost calculation. JSON output to `metrics.jsonl`. **Visibility: Not done.** Metrics write to file only — not surfaced in the REPL after each turn. **Budget enforcement: Not done.** No `SessionBudgetUSD` config, no warnings, no hard stops. |
| **Code location** | `src/micro_x_agent_loop/metrics.py`; `src/micro_x_agent_loop/usage.py` |
| **Plan** | [`PLAN-cost-metrics-logging.md`](../planning/PLAN-cost-metrics-logging.md) — completed. REPL display and budget enforcement are listed as remaining gaps in that plan. |
| **Residual gaps** | (a) Per-turn cost summary not shown in REPL. (b) No `SessionBudgetUSD` with warn/stop logic. Both are straightforward additions on top of existing metrics infrastructure. |
| **Action taken** | — |

---

## Strategy 5 — Tool Result Size Reduction

**Principle:** Tool results (web fetches, file reads, API responses) are the dominant per-turn input cost driver in tool-heavy workflows. Return only decision-relevant content.

| Attribute | Detail |
|-----------|--------|
| **Status** | ⚠️ Partial |
| **Review finding** | **Hard truncation: Done.** `_truncate_tool_result` caps at `MaxToolResultChars: 40000`. **Semantic extraction: Not done.** No per-tool structured extraction — tools return raw API/HTML-derived text. **Summarisation: Implemented but deprecated.** `ToolResultSummarizationEnabled` (default: `false`) — ADR-013 documents that lossy summarisation drops data the main model needs. Formally deprecated and not recommended. |
| **Code location** | `src/micro_x_agent_loop/turn_engine.py` lines 360–391 |
| **Config** | `MaxToolResultChars: 40000`, `ToolResultSummarizationEnabled: false` |
| **ADR** | [ADR-013](../architecture/decisions/) — tool result summarisation unreliable; root cause is unstructured results with no schema to guide extraction |
| **Residual gaps** | Real fix requires tools to return structured JSON (ADR-014 decision outstanding). Until then, no reliable per-tool extraction is possible. |
| **Action taken** | — |

---

## Strategy 6 — Tool Result Data Format (Structured vs Unstructured)

**Principle:** If tool results are structured (JSON), the agent can reliably extract fields. This unblocks both semantic extraction and compiled mode execution.

| Attribute | Detail |
|-----------|--------|
| **Status** | 🔲 Planned (decision pending) |
| **Review finding** | ADR-014 identifies the constraint: MCP tool results are currently unstructured text. Three options documented: (A) own tools return JSON, (B) LLM extracts from text, (C) hybrid. Decision deferred — blocks Strategy 5 (structured extraction) and Strategy 11 (compiled mode). |
| **ADR** | [ADR-014](../architecture/decisions/) — open decision |
| **Residual gaps** | No decision made. Recommended path: Option C (JSON from our own tools, LLM fallback for third-party MCP servers). |
| **Action taken** | — |

---

## Strategy 7 — Sub-Agent Delegation to Cheaper Models

**Principle:** Delegate parallelisable sub-tasks (file search, web lookup, data extraction) to cheap sub-agents with fresh, small contexts instead of doing everything in the main expensive context.

| Attribute | Detail |
|-----------|--------|
| **Status** | ⚠️ Partial |
| **Review finding** | Architecture fully implemented: `SubAgentRunner`, `spawn_subagent` pseudo-tool, configurable sub-agent model and limits. Disabled by default (`SubAgentsEnabled: false`). No default task routing policy — agent doesn't automatically delegate. |
| **Code location** | `src/micro_x_agent_loop/sub_agent.py`; `src/micro_x_agent_loop/agent.py` lines 94–108 |
| **Config** | `SubAgentsEnabled`, `SubAgentModel`, `SubAgentTimeout: 30`, `SubAgentMaxTurns: 15`, `SubAgentMaxTokens: 32768` |
| **Estimated impact** | 40–70% cost reduction for delegated sub-tasks. |
| **Residual gaps** | No guidance for when the LLM should use `spawn_subagent`. No default policy routing simple exploration tasks to sub-agents. Needs system prompt directive and evaluation of task types that benefit from delegation. |
| **Action taken** | — |

---

## Strategy 8 — Per-Turn Model Routing

**Principle:** Route simple turns (formatting, reading a file, extracting a field) to a cheap model rather than using Sonnet for every call.

| Attribute | Detail |
|-----------|--------|
| **Status** | 🔲 Planned (Phase 3) |
| **Review finding** | Multi-provider factory exists (ADR-010) and per-session model config works. Stage 2 classification detects task type signals. But: no per-turn routing logic exists — every call goes to the configured main model. Classification results are diagnostic only and don't influence model selection. |
| **Code location** | `src/micro_x_agent_loop/mode_selector.py`; `src/micro_x_agent_loop/providers/` |
| **Plan** | Listed as Tier 2 Lever #5 in `PLAN-cost-reduction.md`. No dedicated plan document. |
| **Estimated impact** | 50–80% cost reduction for turns that don't need Sonnet capability. |
| **Residual gaps** | (a) No classification scheme for turn complexity. (b) No per-turn model selection logic in `TurnEngine`. (c) Quality degradation risk not evaluated. (d) `Stage2Model` defaults to main model — using Haiku for classification itself would be a cheap quick win. |
| **Action taken** | — |

---

## Strategy 9 — Output Token Reduction

**Principle:** Output tokens are 5× more expensive than input ($15 vs $3 per MTok for Sonnet). Reducing verbosity directly cuts the most expensive token class.

| Attribute | Detail |
|-----------|--------|
| **Status** | ⚠️ Partial |
| **Review finding** | `ConciseOutputEnabled` config appends a system directive to minimise output tokens. Disabled by default. No per-turn adaptive `MaxTokens`. No measurement of actual output token distribution to know if the model is being unnecessarily verbose. |
| **Code location** | `src/micro_x_agent_loop/system_prompt.py` |
| **Config** | `ConciseOutputEnabled: false`, `MaxTokens: 32768` |
| **Residual gaps** | No data on whether the model over-produces output. `MaxTokens: 32768` is generous — many turns need far fewer. Enabling `ConciseOutputEnabled` is a zero-cost configuration change worth evaluating. |
| **Action taken** | — |

---

## Strategy 10 — On-Demand Tool Discovery (Schema Token Reduction)

**Principle:** For large tool sets, don't send all tool schemas every turn. Let the model request only the tools it needs via a discovery pseudo-tool.

| Attribute | Detail |
|-----------|--------|
| **Status** | ⚠️ Partial |
| **Review finding** | Fully implemented: `tool_search` pseudo-tool with on-demand discovery, triggers at >50 tools. Disabled by default (`ToolSearchEnabled: "false"`). Static tool groups and vector-DB semantic routing not implemented. Provider-aware filtering (more aggressive for OpenAI) not implemented. |
| **Code location** | `src/micro_x_agent_loop/tool_search.py` |
| **Config** | `ToolSearchEnabled: "false"` (options: `"auto"`, `"true"`, `"false"`) |
| **Research** | [`kv-cache-and-mcp-tool-routing.md`](../research/kv-cache-and-mcp-tool-routing.md) — full cost modelling. Key insight: Anthropic's 90% cache discount makes full-set schema caching cheap (~$0.001/turn); OpenAI's 50–75% discount makes routing worthwhile even at ~60 tools. |
| **Residual gaps** | No static tool group config. No vector routing. No provider-aware policy. Effort-benefit depends heavily on provider — low priority for Anthropic, higher for OpenAI. |
| **Action taken** | — |

---

## Strategy 11 — Compiled Mode / Batch Execution

**Principle:** For structured, repeatable tasks (batch scoring, data extraction pipelines), compile prompts to deterministic code rather than running full LLM inference for every item.

| Attribute | Detail |
|-----------|--------|
| **Status** | 🔲 Planned (Phase 4+, blocked) |
| **Review finding** | Stage 1 (pattern matching) and Stage 2 (LLM classification) both detect batch/scoring/structured-output signals. Detection is diagnostic only — no compiled execution path exists. Mode analysis is disabled by default (`ModeAnalysisEnabled: false`). |
| **Code location** | `src/micro_x_agent_loop/mode_selector.py` |
| **Config** | `ModeAnalysisEnabled: false`, `Stage2ClassificationEnabled: true` |
| **Blockers** | ADR-014 (tool data format decision) must be resolved first. Compiled mode requires structured tool outputs. |
| **Residual gaps** | No execution path. No plan document for compiled mode beyond detection. Significant architectural work required. |
| **Action taken** | — |

---

## Strategy 12 — Batch API for Autonomous Jobs

**Principle:** The Anthropic Batch API charges 50% of standard pricing for asynchronous requests. Scheduled `--run` jobs (broker mode) are natural candidates.

| Attribute | Detail |
|-----------|--------|
| **Status** | ❌ Gap |
| **Review finding** | Not implemented and not in any planning document. The broker's `--run` mode is non-interactive and therefore compatible with async batch processing. No architectural support exists for accumulating requests or polling batch results. |
| **Code location** | `src/micro_x_agent_loop/broker/` |
| **Residual gaps** | Requires: (a) `AnthropicProvider` batch submission path, (b) async result polling in broker dispatcher, (c) config to opt broker jobs into batch mode. Medium-to-high architectural effort. |
| **Action taken** | — |

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
| 4 | Cost tracking and visibility | ⚠️ Partial | **High** — REPL display + budget caps are quick wins on existing infrastructure | — |
| 5 | Tool result size reduction | ⚠️ Partial | Medium — blocked on ADR-014 for real fix; hard truncation is active | — |
| 6 | Tool result data format (ADR-014) | 🔲 Planned | **High** — blocks strategies 5, 11 | — |
| 7 | Sub-agent delegation | ⚠️ Partial | Medium — architecture done; needs routing policy and system prompt guidance | — |
| 8 | Per-turn model routing | 🔲 Planned | **High** — architecture ready; 50–80% saving on simple turns | — |
| 9 | Output token reduction | ⚠️ Partial | Low — `ConciseOutputEnabled` exists but disabled; evaluate enabling | — |
| 10 | On-demand tool discovery | ⚠️ Partial | Low (Anthropic) / Medium (OpenAI) — provider-dependent | — |
| 11 | Compiled mode / batch execution | 🔲 Planned | Low — Phase 4+, blocked on ADR-014 | — |
| 12 | Batch API for broker jobs | ❌ Gap | Medium — 50% discount, natural fit for `--run` mode | — |
| 13 | Provider and model arbitrage | ⚠️ Partial | Low — OpenAI exists; no benchmarking or auto-switching | — |
| 14 | Retry cost reduction | ❌ Gap | Low — worst-case only, low practical impact | — |

### Top Unaddressed Opportunities

1. **Per-turn cost display in REPL** — metrics exist, just not surfaced. Quick win.
2. **Session budget caps** — `SessionBudgetUSD` with warn/hard-stop on existing `SessionAccumulator`.
3. **ADR-014 decision** — resolves the blocker for strategies 5, 6, 11.
4. **Per-turn model routing** — connect Stage 2 classification output to actual model selection in `TurnEngine`.
5. **Batch API for broker** — 50% cost reduction for all scheduled `--run` jobs, no quality tradeoff.
6. **`Stage2Model` → Haiku** — the classification call itself uses the main model by default; routing it to Haiku is a one-line config change.
