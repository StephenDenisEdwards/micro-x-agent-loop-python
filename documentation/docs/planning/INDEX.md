# Planning Index

Last updated: 2026-03-13

## Priority Queue

What to work on next, in order. Rationale: infrastructure (metrics, broker, API server, publishing channels) is complete. Focus now shifts to **cost reduction** — the [cost reduction review](../review/cost-reduction-review.md) (2026-03-12) identified 14 strategies, 3 fully done, 6 partial, and 5 unstarted. Quick wins first, then architectural work.

| Priority | Plan | Status | Manual Test | Tested | Notes |
|----------|------|--------|-------------|--------|-------|
| **1** | [Cost Metrics Logging](PLAN-cost-metrics-logging.md) | **Completed** | — | — | Prerequisite for all cost work |
| **2** | [Cost Reduction](PLAN-cost-reduction.md) - Phase 1 | **Completed** | [prompt-caching](../testing/MANUAL-TEST-prompt-caching.md) · [compaction-model](../testing/MANUAL-TEST-compaction-model.md) | — | Prompt caching, cheap compaction model |
| **3** | [Cost Reduction](PLAN-cost-reduction.md) - Phase 2 | **Completed** | [compaction-strategy](../testing/MANUAL-TEST-compaction-strategy.md) | — | Tool result reduction, smarter compaction, output reduction |
| **4** | [CLI Status Bar](PLAN-cli-status-bar.md) | **Completed** | — | — | Per-turn cost/token visibility in REPL |
| **5** | [Externalise Pricing Data](PLAN-externalise-pricing-data.md) | **Completed** | [pricing](../testing/MANUAL-TEST-pricing.md) | — | Config.json Pricing key; no hardcoded defaults |
| **6** | [Cost Reduction](PLAN-cost-reduction.md) - QW-1: Stage2Model → Haiku | **Completed** | [stage2-haiku](../testing/MANUAL-TEST-stage2-model-haiku.md) | 🔴 | `config-base.json` → `claude-haiku-4-5-20251001` |
| **7** | [Cost Reduction](PLAN-cost-reduction.md) - QW-2: ConciseOutputEnabled | **Completed** | [concise-output](../testing/MANUAL-TEST-concise-output.md) | 🔴 | Already enabled in `config-base.json` |
| **8** | [Sub-Agents](PLAN-sub-agents.md) - Phase 2a+2b (routing policy, observability) | **Completed** | [sub-agents](../testing/MANUAL-TEST-sub-agents.md) | 🔴 | Routing directive rewritten, enabled by default, memory tracking added. Delivers QW-3 |
| **9** | [Cost Reduction](PLAN-cost-reduction.md) - Phase 2.5a: Session budget caps | **Completed** | [session-budget](../testing/MANUAL-TEST-session-budget.md) | 🔴 | `SessionBudgetUSD` warn at 80%, hard stop at 100% |
| **10** | [Cost Reduction](PLAN-cost-reduction.md) - Phase 3a: ADR-014 decision | **Completed** | — | — | Option C accepted; already implemented (`ToolResult.structured`, `ToolResultFormatter`) |
| **11** | [Cost Reduction](PLAN-cost-reduction.md) - Phase 3b: Per-turn model routing | **Completed** | [per-turn-routing](../testing/MANUAL-TEST-per-turn-routing.md) | 🔴 | Heuristic classifier, opt-in via `PerTurnRoutingEnabled` |
| ~~12~~ | ~~[Cost Reduction](PLAN-cost-reduction.md) - Phase 3c: Batch API for broker~~ | **Dropped** | — | — | Incompatible with multi-turn agentic loops |
| **13** | [Cache-Preserving Tool Routing](PLAN-cache-preserving-tool-routing.md) | **Phase 1 Completed** | [tool-search-and-canonicalisation](../testing/MANUAL-TEST-tool-search-and-canonicalisation.md) | 🔴 | Canonical serialisation + provider-aware tool search. Lanes shelved |
| **14** | [Multi-Provider Support](PLAN-multi-provider.md) | Planned | — | — | Gemini + DeepSeek providers |
| **15** | [End-User Deployment](PLAN-end-user-deployment.md) | Draft | — | — | Frictionless onboarding |
| **16** | [Browser Automation](PLAN-browser-automation.md) | Planned | — | — | Phase 3 of web tooling |
| **17** | [Cloud File Systems](PLAN-cloud-file-systems.md) | Planned | — | — | Nice-to-have |
| **18** | [MCP Mutation Tracking](PLAN-mcp-mutation-tracking.md) | Planned | — | — | Opt-in checkpoint tracking |
| — | [Reddit MCP](PLAN-reddit-mcp.md) | **Blocked** | — | — | Reddit dev registration inaccessible |
| — | ~~[OpenClaw-Like Gateway](PLAN-openclaw-like-gateway-architecture.md)~~ | **Superseded** | — | — | Replaced by Trigger Broker |

<details>
<summary>Completed priorities (click to expand)</summary>

| Priority | Plan | Status |
|----------|------|--------|
| — | [Memory System](PLAN-claude-style-memory.md) | Completed |
| — | [Cross-Session User Memory](PLAN-cross-session-user-memory.md) | Completed |
| — | [LinkedIn Publishing MCP](PLAN-linkedin-publishing-mcp.md) | Completed |
| — | [Dev.to Publishing MCP](PLAN-devto-publishing-mcp.md) | Completed |
| — | [X/Twitter MCP](PLAN-x-twitter-mcp.md) | Completed |
| — | [GitHub Discussions Tool](PLAN-github-discussions-tool.md) | Completed |
| — | [Trigger Broker](PLAN-trigger-broker.md) | Completed |
| — | [Agent API Server](PLAN-agent-api-server.md) | Completed |
| — | [Markdown Rendering](PLAN-markdown-rendering.md) | Completed |
| — | [Test Coverage 90%](PLAN-test-coverage-90.md) | Completed |
| — | [TypeScript Codegen Template](PLAN-typescript-codegen-template.md) | Completed |
| — | [Codegen Parameterisation](PLAN-codegen-parameterisation.md) | Completed |
| — | [Codegen Hardening](PLAN-codegen-hardening.md) | Completed |

</details>


---

## Plan Status Summary

| Status | Count |
|--------|-------|
| Completed | 33 |
| Phase 2a Completed (remaining phases pending) | 1 |
| Blocked | 1 |
| Superseded | 1 |
| Draft | 1 |
| Planning | 1 |
| Dropped | 1 |
| Planned | 5 |

## All Plans

| Plan | Status | Notes |
|------|--------|-------|
| [Web Fetch Tool](PLAN-web-fetch-tool.md) | Completed | Completed 2026-02-18 |
| [Web Search Tool](PLAN-web-search-tool.md) | Completed | Phase 2 of web tooling |
| [WhatsApp Contact Names](PLAN-whatsapp-contact-names.md) | Completed | Completed 2026-02-19 |
| [GitHub Tools](PLAN-github-tools.md) | Completed | Phase 1 done (5 core tools), Phase 2 partial (get_file + search_code) |
| [Interview Assist MCP](PLAN-interview-assist-mcp.md) | Completed | Phase 1 + STT extension, updated 2026-02-19 |
| [Memory System](PLAN-claude-style-memory.md) | Completed | All phases done. MCP mutation tracking extracted to [own plan](PLAN-mcp-mutation-tracking.md) |
| [Continuous Voice Agent](PLAN-continuous-voice-agent.md) | Completed | Phases 1-4 done. Optional future hardening: debounce, noise filters, crash recovery, confidence gating |
| [Cost Reduction](PLAN-cost-reduction.md) | Phases 1–3b Completed — 3c Dropped | 14 strategies reviewed ([cost-reduction-review.md](../review/cost-reduction-review.md)). QW-1/2/3, session budgets, ADR-014, per-turn routing done. Batch API (3c) dropped — incompatible with agentic loops |
| [Cost Metrics Logging](PLAN-cost-metrics-logging.md) | Completed | Structured metrics for cost analysis - prerequisite for cost reduction. See [DESIGN-cost-metrics.md](../design/DESIGN-cost-metrics.md) |
| [Browser Automation](PLAN-browser-automation.md) | Planned | Phase 3 of web tooling |
| [Cloud File Systems](PLAN-cloud-file-systems.md) | Planned | |
| [Cross-Session User Memory](PLAN-cross-session-user-memory.md) | Completed | All phases done: read path, save_memory tool, /memory commands |
| [MCP Mutation Tracking](PLAN-mcp-mutation-tracking.md) | Planned | Opt-in checkpoint tracking for MCP tools via config-declared path params |
| [Mode Selection - LLM Classification](PLAN-mode-selection-llm-classification.md) | Completed | Phase 2 complete. Phase 4 requires tools to return JSON - see [ADR-014](../architecture/decisions/ADR-014-mcp-unstructured-data-constraint.md) |
| [OpenClaw-Like Gateway](PLAN-openclaw-like-gateway-architecture.md) | Superseded | Replaced by [Trigger Broker](PLAN-trigger-broker.md) - retained as reference for full gateway capabilities |
| [Trigger Broker](PLAN-trigger-broker.md) | Completed | Always-on run dispatcher with cron, webhooks, messaging channels, HITL, retries, missed-run recovery, auth |
| [Cache-Preserving Tool Routing](PLAN-cache-preserving-tool-routing.md) | Phase 1 Completed | Canonical serialisation + provider-aware tool search. Lane routing shelved |
| [Sub-Agents](PLAN-sub-agents.md) | Phase 2b Completed — Phase 3+ remaining | Phases 1–2b done: architecture, routing policy, enabled by default, memory tracking. Remaining: async via broker, custom types |
| [Codegen Prompt Discipline](PLAN-codegen-prompt-discipline.md) | Completed | Tightened codegen prompt, added infra file deny, compact output format |
| [LinkedIn Publishing MCP](PLAN-linkedin-publishing-mcp.md) | Completed | Draft-post, draft-article, publish-draft tools |
| [Dev.to Publishing MCP](PLAN-devto-publishing-mcp.md) | Completed | Long-form blog publishing via Forem API. Completed 2026-03-06 |
| [Reddit MCP](PLAN-reddit-mcp.md) | Blocked | Reddit developer registration inaccessible |
| [X/Twitter MCP](PLAN-x-twitter-mcp.md) | Completed | Tweet/thread publishing via X API v2. Completed 2026-03-06 |
| [GitHub Discussions Tool](PLAN-github-discussions-tool.md) | Completed | 5 tools: create, list, get, comment, categories. Completed 2026-03-06 |
| [Agent API Server](PLAN-agent-api-server.md) | Completed | All 5 phases done: AgentChannel, server, broker convergence, CLI client, SDK |
| [Markdown Rendering](PLAN-markdown-rendering.md) | Completed | Progressive markdown rendering in CLI using rich - buffer-and-rerender pattern |
| [Tool Search](PLAN-tool-search.md) | Completed | On-demand tool discovery for large tool sets - defers schemas until needed |
| [Ask User](PLAN-ask-user.md) | Completed | `ask_user` pseudo-tool for mid-execution clarification questions |
| [MCP Server Reimplementation](PLAN-mcp-server-reimplementation.md) | Completed | Reimplemented all tools as TypeScript MCP servers |
| [Test Coverage 90%](PLAN-test-coverage-90.md) | Completed | 59% -> 85% coverage (acceptable threshold) |
| [End-User Deployment](PLAN-end-user-deployment.md) | Draft | Interactive setup wizard for non-expert users |
| [Codegen Agentic Loop](PLAN-codegen-agentic-loop.md) | Completed | Mini agentic loop inside the codegen server for file reading and multi-turn generation |
| [TypeScript Codegen Template](PLAN-typescript-codegen-template.md) | Completed | Migrate codegen template from Python to TypeScript to fix Windows subprocess/venv issues |
| [Codegen Parameterisation](PLAN-codegen-parameterisation.md) | Completed | Typed MCP server generation, manifest registration, and on-demand tool discovery. Completed 2026-03-11 |
| [Codegen Hardening](PLAN-codegen-hardening.md) | Completed | Follow-up robustness and correctness fixes for the codegen server. Completed 2026-03-11 |
| [CLI Status Bar](PLAN-cli-status-bar.md) | Completed | Per-turn cost/token visibility via prompt_toolkit bottom_toolbar. Completed 2026-03-12 |
| [Externalise Pricing Data](PLAN-externalise-pricing-data.md) | Completed | Config.json Pricing key overlays hardcoded defaults; unknown-model warnings. Completed 2026-03-12 |
| [Multi-Provider Support](PLAN-multi-provider.md) | Planned | Gemini + DeepSeek providers |
