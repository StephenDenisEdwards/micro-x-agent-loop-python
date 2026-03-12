# Plan: Provider-Aware Tool Search + Canonical Tool Serialisation

## Status

**Phase 1 Completed** — Canonical serialisation + provider-aware tool search. Lane routing (Phase 2/3) **shelved** — marginal savings ($0.017/session on Anthropic) don't justify config complexity.

## Context

The original plan was lane-based tool routing — grouping tools into fixed sets to reduce schema tokens. After cost analysis:

1. **Lane routing overlaps with tool search** — both reduce tool schema tokens, but lanes add config complexity for marginal savings ($0.017/session on Anthropic)
2. **The optimal strategy is provider-dependent** — Anthropic's 90% cache discount means sending all tools cached is cheapest; OpenAI's 50–75% discount means tool search saves money
3. **Tool search was hurting Anthropic** — it changes the tool prefix every turn, breaking the cache

The revised approach: make tool search provider-aware, and ensure canonical tool ordering for cache stability.

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
- **Anthropic:** return `False` (send all tools, rely on 90% cache discount)
- **OpenAI / other:** apply the existing token threshold logic

Explicit `"true"` / `"false"` still override regardless of provider.

**Files changed:**
- `src/micro_x_agent_loop/tool_search.py` — `provider` kwarg on `should_activate_tool_search()`
- `src/micro_x_agent_loop/agent.py` — passes `config.provider` to `should_activate_tool_search()`
- `config-base.json` — `ToolSearchEnabled` changed from `"true"` to `"auto"` (provider decides)
- `tests/test_tool_search.py` — 7 new provider-aware tests

## Phase 2: Static Lane Routing (Shelved)

Lane-based routing was the original Phase 2: define tool groups in config, route by keyword, preserve cache within each lane. After analysis, the savings ($0.017/session on Anthropic) don't justify the configuration complexity and the risk of routing errors. The combination of canonical serialisation + provider-aware tool search achieves the important wins without new abstractions.

If OpenAI becomes the primary provider or the tool set grows significantly (200+ tools), lane routing could be revisited.

## Phase 3: LLM-Based Router (Shelved)

Depended on Phase 2. Not needed.

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
- **Anthropic:** tool search disabled in auto mode → cache stays stable → saves the cache-write penalty that tool search was causing (~$0.003–0.005/turn)
- **OpenAI:** tool search active when schemas exceed threshold → saves schema tokens at 50% cached rate

## Related

- [DESIGN: Cache-Preserving Tool Routing](../design/DESIGN-cache-preserving-tool-routing.md) — original architecture (lane routing shelved)
- [KV Cache and MCP Tool Routing Research](../research/kv-cache-and-mcp-tool-routing.md) — cost modelling
- [PLAN: Cost Reduction](PLAN-cost-reduction.md) — levers #1 and #7
- [DESIGN: Tool System](../design/DESIGN-tool-system.md) — current tool architecture
