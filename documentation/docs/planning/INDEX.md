# Planning Index

Last updated: 2026-06-02 (Observability plan — now 8 phases: **Phase 0 (emit-path consolidation, [ADR-026](../architecture/decisions/ADR-026-single-event-log-projections-not-parallel-writers.md)) added** after a write-path audit found three parallel emit abstractions recording the same facts; Phases 1–7 production-grade observability + session step-through, framework in [observability-for-ai-agents.md](../best-practice/observability-for-ai-agents.md))

## Priority Queue

What to work on next, in order. **In progress:** [Publish MCP Servers to npm](PLAN-publish-mcp-servers-to-npm.md) — Phase 1 (canary: `shared` + `echo`) code-complete, pending npm scope registration and publish.

Rationale: infrastructure (metrics, broker, API server, publishing channels) is complete. Focus now shifts to **cost reduction** — the [cost reduction review](../review/cost-reduction-review.md) (2026-03-12) identified 14 strategies, 3 fully done, 6 partial, and 5 unstarted. Quick wins first, then architectural work.

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
| ~~11~~ | ~~[Cost Reduction](PLAN-cost-reduction.md) - Phase 3b: Per-turn model routing~~ | **Removed** | — | — | Superseded by semantic routing (2026-04). Binary heuristic lacked task-type granularity and multi-provider support. |
| ~~12~~ | ~~[Cost Reduction](PLAN-cost-reduction.md) - Phase 3c: Batch API for broker~~ | **Dropped** | — | — | Incompatible with multi-turn agentic loops |
| **13** | [Cache-Preserving Tool Routing](PLAN-cache-preserving-tool-routing.md) | **Completed** | [tool-search-and-canonicalisation](../testing/MANUAL-TEST-tool-search-and-canonicalisation.md) | 🔴 | Canonical serialisation + provider-aware tool search. Lanes permanently shelved |
| **14** | [Multi-Provider Support](PLAN-multi-provider.md) | **Completed** | — | — | Gemini + DeepSeek providers |
| **15** | [End-User Deployment](PLAN-end-user-deployment.md) | Draft | — | — | Frictionless onboarding |
| **16** | [Browser Automation](PLAN-browser-automation.md) | Planned | — | — | Phase 3 of web tooling |
| **17** | [Cloud File Systems](PLAN-cloud-file-systems.md) | Planned | — | — | Nice-to-have |
| **18** | [MCP Mutation Tracking](PLAN-mcp-mutation-tracking.md) | Planned | — | — | Opt-in checkpoint tracking |
| **19** | [Semantic Model Routing](PLAN-semantic-model-routing.md) | **Completed** | [semantic-routing](../testing/MANUAL-TEST-semantic-routing.md) | 🔴 | Cross-provider semantic routing: rule→keywords→LLM classifier, provider pool, cache-aware dispatch, feedback loop |
| **20** | [Routing Simplification](PLAN-routing-simplification.md) | **In Progress** | — | — | Bug fixes applied (5 of 10 critical issues fixed). Architectural simplification (Options A–D) still pending. |
| — | [Reddit MCP](PLAN-reddit-mcp.md) | **Blocked** | — | — | Reddit dev registration inaccessible |
| **21** | [Textual TUI](PLAN-textual-tui.md) | **Completed** | — | — | Opt-in Textual-based TUI (`--tui`), all 5 phases. [ADR-022](../architecture/decisions/ADR-022-textual-tui-for-cli.md) |
| **22** | [Task Decomposition](PLAN-task-decomposition.md) | **Completed** | — | — | All 8 phases: MVP, hooks, multi-agent, TUI, session persistence, parallel execution |
| **23** | [Local Model Ecosystems](PLAN-local-model-ecosystems.md) | Planned | — | — | Generic openai-compatible provider + named shortcuts for vLLM, LM Studio, LocalAI, etc. |
| **24** | [Publish MCP Servers to npm](PLAN-publish-mcp-servers-to-npm.md) | **In Progress** | — | — | Phase 1 code-complete (shared + echo). Pending: npm scope registration + publish. |
| **25** | [Shared MCP via HTTP transport](PLAN-shared-mcp-http-transport.md) | **Completed** | — | — | Resolved [ISSUE-006](../issues/ISSUE-006-playwright-profile-contention.md). All 4 phases delivered. End-to-end smoke test discovered 23 Playwright tools over SSE; clean process-tree shutdown on Windows via taskkill /T. |
| **26** | [JobServe MCP Server](PLAN-jobserve-mcp.md) | Planned | — | — | Replaces the failed `tools/jobserve_apply/` codegen experiment with a hand-written first-party MCP server that wraps the JobServe apply flow. Same architectural pattern as gmail/linkedin/web/github MCPs. ~1.5–2 days. |
| **27** | [Behavioural Eval Suite](PLAN-behavioural-eval-suite.md) | Planned | — | — | Implements [ISSUE-007](../issues/ISSUE-007-prose-contract-drift-across-policy-layers.md) Option A as DIY pytest + `BufferedChannel` (Inspect AI deferred to optional Phase 4 — reversal rationale recorded in plan/issue). Phases 0–1 (harness + first regression eval) close the open ISSUE-007 web_fetch/routing tail behind a failing test. Highest-leverage mitigation for prose-contract drift; gates future directive/MCP/routing changes green-red. |
| **28** | [Codegen Multi-Tool](PLAN-codegen-multi-tool.md) | **Completed** | — | — | TypeScript codegen template now supports `TOOLS: ToolDef[]` for multi-tool task apps. Legacy single-tool shape unchanged. Adapter in sealed `index.ts`; `--describe` output keeps singular fields for single-tool back-compat. |
| **29** | [Observability](PLAN-observability.md) | **In Progress** | — | — | Production-grade observability + session step-through. 8 phases. **Phase 0 — unify the emit path — Implemented 2026-06-03** (one authoritative `events` log; `metrics.jsonl` + `routing_feedback.db` now projections, not parallel writers; triple-write removed; [ADR-026](../architecture/decisions/ADR-026-single-event-log-projections-not-parallel-writers.md) Accepted). Remaining (Planned): step-through MVP (emit `llm.call`/`routing.decision`/`mode.analyzed`/`session.config`), `/replay` command, PII redaction, OTel exporter, alerting, online eval harness, cost rollups + sampling. |
| **30** | [Gemma Model Support](PLAN-gemma-model-support.md) | **In Progress** | — | — | **Phase 1 (Path C, Google-hosted) Completed 2026-05-30** — new `config-standard-gemma-cloud.json` profile (defaults to `gemma-3-12b-it` for free-tier safety), `tests/providers/test_gemma_via_gemini.py` offline + live-smoke tests. **Phase 2 (Path A, Ollama local) Completed 2026-05-29** — `SystemPromptCompact`/`SystemPromptExtras` config surface, `gemma_unparsed.*` metrics, `config-standard-ollama-gemma3.json` profile. Live-validated end-to-end on RTX 3050 Ti / Ollama 0.24. **Headline local model swapped from `gemma3:4b` to `orieg/gemma3-tools:4b-ft`** after discovering Ollama hard-rejects `tools=` for stock gemma3. **Phase 3 (vLLM) postponed** — not viable on 4 GB Windows hardware. Phase 4 (native GemmaProvider) not triggered. |
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
| — | [Filesystem Navigation](PLAN-filesystem-navigation.md) | Completed 2026-05-09 — all 6 active phases (1, 2, 2b, 3, 3b, 4, 5) shipped; Phase 6 (image/PDF/notebook) deferred until a use case appears; ISSUE-005 resolved in accident-prevention scope |

</details>


---

## Plan Status Summary

| Status | Count |
|--------|-------|
| Completed | 39 |
| Review | 1 |
| In Progress | 4 |
| Blocked | 1 |
| Superseded | 1 |
| Draft | 1 |
| Dropped | 1 |
| Planned | 6 |
| Research | 1 |

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
| [Cost Reduction](PLAN-cost-reduction.md) | Phases 1–3a Completed, 3b Removed, 3c Dropped | 14 strategies reviewed ([cost-reduction-review.md](../review/cost-reduction-review.md)). QW-1/2/3, session budgets, ADR-014 done. Per-turn routing (3b) removed — superseded by semantic routing. Batch API (3c) dropped — incompatible with agentic loops |
| [Cost Metrics Logging](PLAN-cost-metrics-logging.md) | Completed | Structured metrics for cost analysis - prerequisite for cost reduction. See [DESIGN-cost-metrics.md](../design/DESIGN-cost-metrics.md) |
| [Browser Automation](PLAN-browser-automation.md) | Planned | Phase 3 of web tooling |
| [Cloud File Systems](PLAN-cloud-file-systems.md) | Planned | |
| [Cross-Session User Memory](PLAN-cross-session-user-memory.md) | Completed | All phases done: read path, save_memory tool, /memory commands |
| [MCP Mutation Tracking](PLAN-mcp-mutation-tracking.md) | Planned | Opt-in checkpoint tracking for MCP tools via config-declared path params |
| [Mode Selection - LLM Classification](PLAN-mode-selection-llm-classification.md) | Completed | Phase 2 complete. Phase 4 requires tools to return JSON - see [ADR-014](../architecture/decisions/ADR-014-mcp-unstructured-data-constraint.md) |
| [OpenClaw-Like Gateway](PLAN-openclaw-like-gateway-architecture.md) | Superseded | Replaced by [Trigger Broker](PLAN-trigger-broker.md) - retained as reference for full gateway capabilities |
| [Trigger Broker](PLAN-trigger-broker.md) | Completed | Always-on run dispatcher with cron, webhooks, messaging channels, HITL, retries, missed-run recovery, auth |
| [Cache-Preserving Tool Routing](PLAN-cache-preserving-tool-routing.md) | Completed | Canonical serialisation + provider-aware tool search. Lanes permanently shelved (see plan for reasoning) |
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
| [Multi-Provider Support](PLAN-multi-provider.md) | Completed | Gemini + DeepSeek providers. Completed 2026-03-13 |
| [Semantic Model Routing](PLAN-semantic-model-routing.md) | Completed | Cross-provider semantic routing with 3-stage classifier, provider pool, cache-aware dispatch, feedback loop. Completed 2026-03-21 |
| [Routing Simplification](PLAN-routing-simplification.md) | In Progress | Bug fixes applied 2026-03-22; architectural simplification pending |
| [Local Model Ecosystems](PLAN-local-model-ecosystems.md) | Planned | Generic openai-compatible provider for vLLM, LM Studio, LocalAI, llama.cpp, Jan, TGI, MLX |
| [Gemma Model Support](PLAN-gemma-model-support.md) | In Progress | Phase 1 (Path C) Completed 2026-05-30: `config-standard-gemma-cloud.json` profile + offline tests; live smoke gated on GEMINI_API_KEY. Phase 2 (Path A) Completed 2026-05-29: `orieg/gemma3-tools:4b-ft` on Ollama 0.24 (stock `gemma3:4b` rejected). Phase 3 (vLLM) postponed — not viable on 4 GB Windows hardware. Phase 4 (native GemmaProvider) not triggered. |
| [Textual TUI](PLAN-textual-tui.md) | Completed | Opt-in Textual-based TUI (`--tui`), all 5 phases. [ADR-022](../architecture/decisions/ADR-022-textual-tui-for-cli.md). Completed 2026-04-02 |
| [Publish MCP Servers to npm](PLAN-publish-mcp-servers-to-npm.md) | In Progress | Phase 1 code-complete (shared + echo). 6 phases: canary, worked example (`google`), fan out, automate. |
| [Shared MCP via HTTP transport](PLAN-shared-mcp-http-transport.md) | Completed | Resolved [ISSUE-006](../issues/ISSUE-006-playwright-profile-contention.md). All 4 phases delivered: SSE/HTTP transport in `mcp_manager.py`, env-var-driven client in `_runtime/mcp-client.ts`, `MICRO_X_<NAME>_MCP_URL` injection in codegen `run_task`, config flip + Windows process-tree termination fix. |
| [JobServe MCP Server](PLAN-jobserve-mcp.md) | Planned | Hand-written first-party MCP server for the JobServe apply flow. Replaces the failed codegen-driven `tools/jobserve_apply/` experiment with the same pattern used by gmail/linkedin/web/github MCPs. |
| [Compiled-Wiki Knowledge Base](PLAN-compiled-wiki-kb.md) | Research | Placeholder reminder — Karpathy-style "compiled wiki" / context-engineering pattern. See [compiled-wiki-knowledge-base.md](../research/compiled-wiki-knowledge-base.md). Zero-code MVP (manual habit + `wiki/` dir + `CLAUDE.md` directive) recommended before any implementation. |
| [Observability](PLAN-observability.md) | In Progress | Production-grade observability + session step-through. Findings audit + 8-phase delivery. Phase 0 emit-path consolidation **implemented 2026-06-03** ([ADR-026](../architecture/decisions/ADR-026-single-event-log-projections-not-parallel-writers.md) Accepted); remaining Planned: step-through MVP, `/replay` command, PII redaction, OTel, alerting, online evals, cost rollups + sampling. Measured against [observability-for-ai-agents.md](../best-practice/observability-for-ai-agents.md). |
