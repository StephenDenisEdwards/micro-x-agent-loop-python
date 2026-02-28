# Planning Index

Last updated: 2026-02-27

## Priority Queue

What to work on next, in order. Rationale: cost reduction is the top priority — every session costs money, so reducing cost has compounding ROI. Metrics come first because you can't validate savings without measurement.

| Priority | Plan | Status | Why this order |
|----------|------|--------|----------------|
| **1** | [Cost Metrics Logging](PLAN-cost-metrics-logging.md) | **Completed** | Prerequisite for all cost work — need baseline measurements first |
| **2** | [Cost Reduction](PLAN-cost-reduction.md) — Phase 1 (Prompt caching, cheap compaction model) | **Completed** | Highest ROI cost levers, low effort, measurable with metrics from P1 |
| **3** | [Cost Reduction](PLAN-cost-reduction.md) — Phase 2 (Tool result reduction, smarter compaction, output reduction) | **Completed** | Next-highest ROI, requires per-tool data from metrics |
| **4** | [Memory System](PLAN-claude-style-memory.md) — Phase 3 remainder | **Completed** | Event callback API + stress tests done; MCP mutation tracking extracted to own plan |
| **5** | [Cross-Session User Memory](PLAN-cross-session-user-memory.md) | **Completed** | All phases done: read path, save_memory tool, /memory commands |
| **6** | [OpenClaw-Like Gateway](PLAN-openclaw-like-gateway-architecture.md) | Planned | Large architectural migration; prerequisite for cost reduction Phase 3 |
| **7** | [Cost Reduction](PLAN-cost-reduction.md) — Phase 3 (Model routing, sub-agents, schema optimisation) | Planning | Architectural changes, higher effort, depends on gateway plan |
| **8** | [Browser Automation](PLAN-browser-automation.md) | Planned | Phase 3 of web tooling |
| **9** | [Cloud File Systems](PLAN-cloud-file-systems.md) | Planned | |
| **10** | [MCP Mutation Tracking](PLAN-mcp-mutation-tracking.md) | Planned | Opt-in checkpoint tracking for MCP tools; extracted from Memory System Phase 3 |

---

## Plan Status Summary

| Status | Count |
|--------|-------|
| Completed | 11 |
| In Progress | 0 |
| Planning | 0 |
| Planned | 4 |

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
| [Cost Reduction](PLAN-cost-reduction.md) | Phase 1 & 2 Completed | 12 prioritised cost levers; Phases 1-2 implemented, Phase 3 planned |
| [Cost Metrics Logging](PLAN-cost-metrics-logging.md) | Completed | Structured metrics for cost analysis — prerequisite for cost reduction. See [DESIGN-cost-metrics.md](../design/DESIGN-cost-metrics.md) |
| [Browser Automation](PLAN-browser-automation.md) | Planned | Phase 3 of web tooling |
| [Cloud File Systems](PLAN-cloud-file-systems.md) | Planned | |
| [Cross-Session User Memory](PLAN-cross-session-user-memory.md) | Completed | All phases done: read path, save_memory tool, /memory commands |
| [MCP Mutation Tracking](PLAN-mcp-mutation-tracking.md) | Planned | Opt-in checkpoint tracking for MCP tools via config-declared path params |
| [Mode Selection — LLM Classification](PLAN-mode-selection-llm-classification.md) | Completed | Phase 2 complete. Phase 4 blocked by [ADR-014](../architecture/decisions/ADR-014-mcp-unstructured-data-constraint.md) (MCP unstructured data) |
| [OpenClaw-Like Gateway](PLAN-openclaw-like-gateway-architecture.md) | Planned | Server/gateway architecture migration |
