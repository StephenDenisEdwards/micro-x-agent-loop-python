# Plan: Provider-Aware Tool Search + Canonical Tool Serialisation

## Status

**Completed** — Phase 1 delivered canonical serialisation + provider-aware tool search. Phases 2/3 (lane routing, LLM router) permanently shelved after cost analysis showed they're unnecessary at the current scale.

---

## The Problem

Every LLM API call includes **all tool definitions** (names, descriptions, parameter schemas). With ~60 MCP tools, that's roughly **6,000 tokens of tool schemas sent on every call**.

In a 10-turn conversation, that's 60,000 tokens of tool schemas — even if the agent only used 3–4 tools. The question is: should we send all tools every time, or only the relevant ones?

## Why the Answer Depends on the Provider

LLM providers cache the beginning (prefix) of each request server-side. If the tool definitions are identical between calls, the provider recognises the prefix and charges a reduced rate. But the discount varies dramatically:

| Provider | Cache read discount | What you pay for cached tokens |
|----------|-------------------|-------------------------------|
| **Anthropic** | 90% off | 10% of full price |
| **OpenAI gpt-4.1** | 75% off | 25% of full price |
| **OpenAI gpt-4o** | 50% off | 50% of full price |

This creates two very different cost profiles for a 10-turn session with ~12,700 tokens of system prompt + tool schemas:

| Provider | Cost (send all tools, cached) |
|----------|------------------------------|
| Anthropic | **$0.027** — cheap, caching almost eliminates the overhead |
| OpenAI gpt-4.1 | **$0.082** — 3x Anthropic |
| OpenAI gpt-4o | **$0.175** — 6.5x Anthropic |

**Key insight:** On Anthropic, sending all tools is nearly free thanks to the 90% cache discount. On OpenAI, those cached tool schemas remain a significant cost because the discount is weaker.

### The cache-breaking trap

Caching only works when the request prefix is **byte-identical** between calls. If you change which tools you send — or even their order — the cache breaks and you pay full price. This means:

- **Sending all tools in a stable order** = cache hits every turn = cheap on Anthropic
- **Sending different tools per turn** = cache misses = expensive, especially on Anthropic where cache-write has a 1.25x surcharge

## The Solution: Provider-Aware Tool Search (Phase 1 — Completed)

Rather than a one-size-fits-all approach, the agent automatically adapts its strategy based on the provider:

### On Anthropic, Gemini, DeepSeek: send all tools, rely on caching

Tool search is **disabled**. All ~60 tool schemas are sent on every call in a canonical (sorted) order. These providers all offer a **90% cache read discount**, making the cached tool prefix nearly free after the first turn. No risk of hiding a tool the LLM needs.

| Provider | Cache Read Discount | Cache Write Surcharge | Caching Mode |
|----------|--------------------|-----------------------|--------------|
| Anthropic | 90% off | 1.25x surcharge | Semi-automatic (breakpoints) |
| Gemini | 90% off | None | Automatic (implicit) |
| DeepSeek | 90% off | None | Fully automatic |

### On OpenAI / other providers: use tool search to send fewer tools

Tool search is **enabled**. Instead of sending all 60 tool schemas, the LLM receives a single `tool_search` tool. When it needs a specific capability, it searches by keyword, and only the matching tool schemas are loaded. This dramatically reduces per-turn token spend where caching discounts are weaker (OpenAI: 50–75% off).

### How it's configured

`ToolSearchEnabled` in config supports three values:
- `"auto"` (default) — provider decides: off for Anthropic/Gemini/DeepSeek (90% cache discount), threshold-based for OpenAI/others
- `"true"` — always on, regardless of provider
- `"false"` — always off

### What was also fixed: canonical tool ordering

Tools were previously serialised in MCP server discovery order (based on startup timing). A server restart could silently change the tool order, breaking the cache. `canonicalise_tools()` now sorts tools by name and recursively sorts schema keys, ensuring byte-stable serialisation regardless of discovery order.

## Prerequisites

- [Cost Metrics Logging](PLAN-cost-metrics-logging.md) — **Completed** — needed to measure cache hit rates
- [Cost Reduction Phase 1](PLAN-cost-reduction.md) — **Completed** — prompt caching must be enabled first

## Phase 1: Canonical Serialisation + Provider-Aware Tool Search (Completed)

### 1a. Canonical tool serialisation (cache stability)

**Problem:** Tools were serialised in MCP discovery order (server startup timing). A server restart silently changed the prefix, breaking the cache. The Anthropic cache marker goes on the last tool — ordering matters.

**Fix:** `canonicalise_tools()` sorts tools by name and recursively sorts schema keys before passing to providers.

**Files changed:**
- `src/micro_x_agent_loop/tool.py` — added `canonicalise_tools()` and `_sort_schema()`
- `src/micro_x_agent_loop/providers/anthropic_provider.py` — `convert_tools()` uses `canonicalise_tools()`
- `src/micro_x_agent_loop/providers/openai_provider.py` — `convert_tools()` uses `canonicalise_tools()`
- `tests/test_tool_canonicalisation.py` — 13 tests: ordering, schema sorting, byte-stability, provider integration

### 1b. Provider-aware `should_activate_tool_search()`

**Problem:** `ToolSearchEnabled: "true"` was a global toggle. On Anthropic it broke caching. On OpenAI it saved money.

**Fix:** Added `provider` parameter to `should_activate_tool_search()`. When `setting == "auto"`:
- **Anthropic, Gemini, DeepSeek:** return `False` (send all tools, rely on 90% cache discount)
- **OpenAI / other:** apply the existing token threshold logic

Explicit `"true"` / `"false"` still override regardless of provider.

**Files changed:**
- `src/micro_x_agent_loop/tool_search.py` — `provider` kwarg on `should_activate_tool_search()`
- `src/micro_x_agent_loop/agent.py` — passes `config.provider` to `should_activate_tool_search()`
- `config-base.json` — `ToolSearchEnabled` changed from `"true"` to `"auto"` (provider decides)
- `tests/test_tool_search.py` — 7 new provider-aware tests

## Phases 2 & 3: Lane Routing and LLM Router (Permanently Shelved)

### What these would have done

- **Phase 2 (Static lane routing):** Pre-define tool groups in config (e.g. `"coding": [filesystem, github, codegen]`, `"research": [web, google]`). The agent picks a group per session, sending only those tool schemas.
- **Phase 3 (LLM-based router):** An LLM call before each turn to intelligently select which tools to include.

### Why they're not needed

1. **Tool search already covers the non-Anthropic case.** On OpenAI and other providers where sending all tools is expensive, tool search dynamically reduces the tool set per turn — no static configuration required.

2. **On Anthropic, sending all tools is already cheap.** The 90% cache discount means the entire tool prefix costs ~$0.001/turn after the first. Lanes would save ~$0.017/session — not worth the complexity.

3. **Lanes add configuration burden with correctness risk.** Someone has to manually maintain the group definitions. If a tool is in the wrong group (or missing from all groups), the LLM can't use it — a silent correctness failure, not just a cost issue.

4. **The LLM router adds latency and cost.** An extra API call per turn to decide which tools to include defeats the purpose when tool search achieves the same result as a side effect of normal tool use.

### When to revisit

These approaches would become worthwhile if:
- A provider with no caching discount becomes primary
- Task types become predictable enough that static groups would outperform dynamic search
- Tool naming conventions diverge enough that keyword search produces too many false matches per query

---

## Verification

1. `python -m pytest tests/test_tool_canonicalisation.py -v` — 13 tests pass
2. `python -m pytest tests/test_tool_search.py -v` — 30 tests pass (including 7 new provider-aware tests)
3. `python -m pytest tests/ -v` — no regressions
4. Manual: `ToolSearchEnabled: "auto"` + `Provider: "anthropic"` → tool search inactive, all tools sent
5. Manual: `ToolSearchEnabled: "auto"` + `Provider: "openai"` → tool search active (if threshold exceeded)
6. Manual: `ToolSearchEnabled: "true"` → tool search active regardless of provider

## Cost Impact

### Canonical serialisation
- Eliminates silent cache breaks from tool ordering drift
- No runtime cost — pure serialisation change

### Provider-aware tool search
- **Anthropic, Gemini, DeepSeek:** tool search disabled in auto mode → cache stays stable → saves the cache-write penalty that tool search was causing (~$0.003–0.005/turn)
- **OpenAI / other:** tool search active when schemas exceed threshold → saves schema tokens at 50–75% cached rate

## Related

- [DESIGN: Cache-Preserving Tool Routing](../design/DESIGN-cache-preserving-tool-routing.md) — original architecture (lane routing shelved)
- [KV Cache and MCP Tool Routing Research](../research/kv-cache-and-mcp-tool-routing.md) — cost modelling
- [PLAN: Cost Reduction](PLAN-cost-reduction.md) — levers #1 and #7
- [DESIGN: Tool System](../design/DESIGN-tool-system.md) — current tool architecture
