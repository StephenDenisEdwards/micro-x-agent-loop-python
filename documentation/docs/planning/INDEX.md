# Planning Index

Last updated: 2026-03-07

## Priority Queue

What to work on next, in order. Rationale: promotional publishing channels (now mostly complete) provided multi-channel reach. Next priority is the trigger broker — enabling scheduled and externally-triggered agent runs (cron, WhatsApp, webhooks). End-user deployment and remaining cost optimisation follow.

| Priority | Plan | Status | Why this order |
|----------|------|--------|----------------|
| **1** | [Cost Metrics Logging](PLAN-cost-metrics-logging.md) | **Completed** | Prerequisite for all cost work — need baseline measurements first |
| **2** | [Cost Reduction](PLAN-cost-reduction.md) — Phase 1 (Prompt caching, cheap compaction model) | **Completed** | Highest ROI cost levers, low effort, measurable with metrics from P1 |
| **3** | [Cost Reduction](PLAN-cost-reduction.md) — Phase 2 (Tool result reduction, smarter compaction, output reduction) | **Completed** | Next-highest ROI, requires per-tool data from metrics |
| **4** | [Memory System](PLAN-claude-style-memory.md) — Phase 3 remainder | **Completed** | Event callback API + stress tests done; MCP mutation tracking extracted to own plan |
| **5** | [Cross-Session User Memory](PLAN-cross-session-user-memory.md) | **Completed** | All phases done: read path, save_memory tool, /memory commands |
| **6** | [LinkedIn Publishing MCP](PLAN-linkedin-publishing-mcp.md) | **Completed** | First promotional channel — highest-priority audience (senior engineers, CTOs) |
| **7** | [Dev.to Publishing MCP](PLAN-devto-publishing-mcp.md) | **Completed** | Simplest auth (API key, no OAuth). Long-form technical content drives deep engagement and is indexable by search engines |
| **8** | [Reddit MCP](PLAN-reddit-mcp.md) | **Blocked** | Reddit developer registration inaccessible — revisit later |
| **9** | [X/Twitter MCP](PLAN-x-twitter-mcp.md) | **Completed** | Good reach but hostile API (PKCE auth, unstable, write-only free tier). Less bang-for-buck than dev.to/Reddit for technical audience |
| **10** | [GitHub Discussions Tool](PLAN-github-discussions-tool.md) | **Completed** | Community building — low value until the project has active users. Extends existing GitHub MCP server |
| ~~11~~ | ~~[OpenClaw-Like Gateway](PLAN-openclaw-like-gateway-architecture.md)~~ | **Superseded** | Replaced by Trigger Broker below — retained as reference for full gateway capabilities |
| **11** | [Trigger Broker](PLAN-trigger-broker.md) | **Completed** | Always-on run dispatcher for cron, webhooks, messaging channels, HITL, retries |
| **12** | [End-User Deployment](PLAN-end-user-deployment.md) | Draft | Frictionless onboarding becomes critical once promotional channels drive traffic to the repo. Benefits from stable post-broker architecture |
| **13** | [Cost Reduction](PLAN-cost-reduction.md) — Phase 3 (Model routing, sub-agents, schema optimisation) | Planning | Architectural changes, higher effort; model routing can be done in TurnEngine/Provider layer without gateway |
| **14** | [Browser Automation](PLAN-browser-automation.md) | Planned | Phase 3 of web tooling |
| **15** | [Cloud File Systems](PLAN-cloud-file-systems.md) | Planned | Nice-to-have, not promotional |
| **16** | [MCP Mutation Tracking](PLAN-mcp-mutation-tracking.md) | Planned | Opt-in checkpoint tracking for MCP tools; internal plumbing |
| **17** | [Cache-Preserving Tool Routing](PLAN-cache-preserving-tool-routing.md) | Planned | Lane-based tool routing that preserves prompt caching; do when cost data justifies it |


---

## Plan Status Summary

| Status | Count |
|--------|-------|
| Completed | 17 |
| Blocked | 1 |
| Superseded | 1 |
| Draft | 1 |
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
| [Mode Selection — LLM Classification](PLAN-mode-selection-llm-classification.md) | Completed | Phase 2 complete. Phase 4 requires tools to return JSON — see [ADR-014](../architecture/decisions/ADR-014-mcp-unstructured-data-constraint.md) |
| [OpenClaw-Like Gateway](PLAN-openclaw-like-gateway-architecture.md) | Superseded | Replaced by [Trigger Broker](PLAN-trigger-broker.md) — retained as reference for full gateway capabilities |
| [Trigger Broker](PLAN-trigger-broker.md) | Completed | Always-on run dispatcher with cron, webhooks, messaging channels, HITL, retries, missed-run recovery, auth |
| [Cache-Preserving Tool Routing](PLAN-cache-preserving-tool-routing.md) | Planned | Lane-based routing preserving prefix caching. See [DESIGN](../design/DESIGN-cache-preserving-tool-routing.md) |
| [Codegen Prompt Discipline](PLAN-codegen-prompt-discipline.md) | Completed | Tightened codegen prompt, added infra file deny, compact output format |
| [LinkedIn Publishing MCP](PLAN-linkedin-publishing-mcp.md) | Completed | Draft-post, draft-article, publish-draft tools |
| [Dev.to Publishing MCP](PLAN-devto-publishing-mcp.md) | Completed | Long-form blog publishing via Forem API. Completed 2026-03-06 |
| [Reddit MCP](PLAN-reddit-mcp.md) | Blocked | Reddit developer registration inaccessible |
| [X/Twitter MCP](PLAN-x-twitter-mcp.md) | Completed | Tweet/thread publishing via X API v2. Completed 2026-03-06 |
| [GitHub Discussions Tool](PLAN-github-discussions-tool.md) | Completed | 5 tools: create, list, get, comment, categories. Completed 2026-03-06 |
| [End-User Deployment](PLAN-end-user-deployment.md) | Draft | Interactive setup wizard for non-expert users |
