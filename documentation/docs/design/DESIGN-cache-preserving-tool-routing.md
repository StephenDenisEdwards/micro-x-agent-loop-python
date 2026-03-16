# Design: Cache-Preserving MCP Tool Routing

## Status

**Planning** — architecture defined, not yet implemented.

## Problem

The agent currently sends all ~60-120 MCP tool schemas on every API call. This works because prompt caching amortises the cost: the system prompt + tool schemas form a stable prefix that gets cached after the first turn, reducing subsequent turns to 10% of base input cost (Anthropic) or 25-50% (OpenAI).

However, as the tool set grows or tasks become more specialised, there's pressure to implement **smart routing** — sending only relevant tools per turn. The danger is that dynamic tool injection **changes the prompt prefix**, causing cache misses. With Anthropic's 1.25x cache-creation surcharge, a cache miss every turn is worse than sending all tools with cache hits.

This document defines an architecture that reduces tool bloat while preserving cross-request prefix caching.

## Background: Two Distinct Caches

### In-Request KV Cache (Always Present)

Every LLM inference request builds a **KV cache** during the prefill phase. For each token in the input, the model computes Key and Value vectors at every layer and attention head. These are stored in GPU memory so that during autoregressive generation, each new output token can attend to all previous tokens without recomputing their K/V from scratch.

**Key properties:**
- Created from scratch for every API request
- Lives only for the duration of that request
- Size: `2 × layers × heads × head_dim × sequence_length` (tens of GB for large models at 100K context)
- Not shared across requests
- Invisible to the developer — entirely infrastructure-level

This cache is **not affected** by tool routing decisions. It exists regardless.

### Cross-Request Prefix Cache (Provider Feature)

Anthropic and OpenAI persist KV cache entries **across requests** on their servers. When a new request's prefix matches a previously-cached prefix byte-for-byte, the provider skips the prefill computation for those tokens and charges a discounted rate.

**Key properties:**
- Prefix-based: the cache matches from the start of the prompt. The first byte that differs invalidates everything after it
- Exact byte match: whitespace changes, field reordering, description edits — all break the cache
- Time-limited: ~5 minutes TTL (both providers)
- Anthropic: explicit `cache_control` markers, 1.25x write premium, 90% read discount
- OpenAI: automatic (no markers), no write premium, 50-75% read discount

**This is the cache that tool routing can defeat.**

### How They Interact

```
Request 1:  [system prompt | tool schemas | conversation]
            |---- prefix cache boundary ----|
            |------------- in-request KV cache ------------|

Request 2:  [system prompt | tool schemas | conversation + new turn]
            |---- prefix cache HIT ---------|--- compute --|
            |------------- in-request KV cache ------------|
```

If the tool schemas change between Request 1 and Request 2, the prefix cache **misses** at the point of divergence. The in-request KV cache still works — it always does — but the provider charges full input rate for all tokens after the divergence point, plus a cache-creation surcharge (Anthropic).

## How Dynamic Tool Injection Defeats Prefix Caching

Any change to the tool list that appears before the conversation history breaks the prefix cache. Specifically:

### 1. Tool Order Changes

```
Turn 1 tools: [filesystem__bash, filesystem__read_file, web__web_search, ...]
Turn 2 tools: [web__web_search, filesystem__bash, filesystem__read_file, ...]
```

Even if the same tools are present, reordering changes the byte sequence. Cache miss from the first reordered tool onward.

### 2. Description Drift

Tool descriptions that include dynamic content (timestamps, session IDs, counts, current state):

```
Turn 1: "Search the web. Rate limit: 8/10 remaining."
Turn 2: "Search the web. Rate limit: 5/10 remaining."
```

Cache miss at the first differing byte in the description.

### 3. Schema Field Differences

Adding optional fields, changing defaults, or including contextual examples in schemas:

```json
// Turn 1
{"type": "object", "properties": {"query": {"type": "string"}}}

// Turn 2 (added "description" to help the model)
{"type": "object", "properties": {"query": {"type": "string", "description": "Search query"}}}
```

### 4. Tools Appearing or Disappearing

The most common routing pattern — sending different tool subsets per turn:

```
Turn 1: [filesystem, codegen]           → cache created for this prefix
Turn 2: [filesystem, codegen, web]      → cache MISS (web tools added)
Turn 3: [filesystem, web]              → cache MISS (codegen removed, different order)
```

Each tool set change creates a new prefix, triggering a cache write (1.25x on Anthropic) and losing the read discount (90% off) on the entire tool section.

### 5. MCP Server Restart

If an MCP server restarts and re-registers tools with slightly different descriptions (e.g., version string in description, different property ordering in JSON schema), the cache breaks silently.

## Architecture: Stable Lanes with Deterministic Routing

### Core Principle

**The tool list sent to the model must be a deterministic function of a small, stable key — not of the user's message content.** This means the prefix stays identical across turns within a "lane", preserving the cache.

### Lane Architecture

A **lane** is a fixed, pre-defined set of tools. Each lane has a stable, canonical tool list that never changes within a session. The routing decision maps a request to a lane, not to an ad-hoc tool subset.

```
                    ┌─────────────────────┐
User message ──────│  Deterministic       │──── Lane ID ───┐
                    │  Router              │                │
                    │  (rules / classifier)│                │
                    └─────────────────────┘                │
                                                           ▼
                    ┌──────────────────────────────────────────┐
                    │  Lane Registry (config.json)             │
                    │                                          │
                    │  "coding"  → [filesystem, codegen, gh]   │
                    │  "research"→ [web, google, linkedin]     │
                    │  "comms"   → [whatsapp, google-comms]    │
                    │  "full"    → [all tools]                 │
                    └──────────────────────────────────────────┘
                                    │
                                    ▼
                    ┌──────────────────────────────────────────┐
                    │  Canonical Tool Serialiser               │
                    │  - Sorted by name (deterministic order)  │
                    │  - Frozen descriptions (versioned)       │
                    │  - No volatile fields                    │
                    └──────────────────────────────────────────┘
                                    │
                                    ▼
                              LLM API call
                       (stable prefix → cache hit)
```

### Why Lanes, Not Per-Turn Selection

| Approach | Prefix Stability | Cache Hit Rate | False-Negative Risk |
|----------|-----------------|----------------|---------------------|
| All tools every turn | Perfect | ~100% after turn 1 | Zero |
| Per-turn vector routing | Poor (changes each turn) | ~0% | High |
| Stable lanes (3-5 groups) | High (changes only on lane switch) | ~90%+ within a lane | Low (groups are broad) |

Lane switches do cause cache misses, but they're infrequent (typically once per session when the task type is established). Within a lane, every turn gets cache hits.

### Deterministic Router (No LLM Required)

The router should operate **outside the LLM** when possible, using deterministic rules:

**Stage 1 — Structural signals (zero cost):**

```python
def select_lane(user_message: str, session_state: SessionState) -> str:
    """Deterministic lane selection. Returns lane ID."""

    # Explicit user override
    if user_message.startswith("/lane "):
        return user_message.split()[1]

    # Sticky: stay in current lane unless overridden
    if session_state.current_lane and not _signals_lane_change(user_message):
        return session_state.current_lane

    # Keyword-based classification
    msg_lower = user_message.lower()

    coding_signals = ["write", "code", "implement", "fix", "bug", "refactor",
                      "file", "function", "class", "test"]
    research_signals = ["search", "find", "look up", "research", "what is",
                        "articles", "papers"]
    comms_signals = ["email", "gmail", "whatsapp", "message", "send", "calendar"]

    scores = {
        "coding": sum(1 for s in coding_signals if s in msg_lower),
        "research": sum(1 for s in research_signals if s in msg_lower),
        "comms": sum(1 for s in comms_signals if s in msg_lower),
    }

    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best

    # Default: full tool set (safest, preserves cache from turn 1)
    return "full"
```

**Stage 2 — LLM classifier (cheap, for ambiguous cases only):**

Only invoked when Stage 1 returns `"full"` and `stage2_routing_enabled` is configured. Uses a small, cheap model (Haiku) with a stable prompt:

```
Router Prompt Template (stable — never changes):
─────────────────────────────────────────────────
You are a task classifier. Given a user message, classify it into exactly one
category. Respond with ONLY the category name, nothing else.

Categories:
- coding: File operations, code generation, debugging, git operations
- research: Web search, information lookup, reading articles
- comms: Email, messaging, calendar, contacts
- full: Unclear or spans multiple categories

User message: {user_message}

Category:
─────────────────────────────────────────────────
```

This prompt is tiny (~80 tokens), uses Haiku (~$0.001 per call), and the response is a single word. Total overhead: ~$0.001 + ~100ms latency.

### Two-Model Pattern (Router + Worker)

For maximum cache efficiency with large tool sets:

```
┌──────────────┐     ┌───────────────────────────────────────────┐
│ Router Model │     │ Worker Model                              │
│ (Haiku)      │     │ (Sonnet/Opus)                             │
│              │     │                                           │
│ Input:       │     │ Input:                                    │
│ - user msg   │────▶│ - system prompt      ◄── STABLE PREFIX    │
│ - lane list  │     │ - lane tool schemas  ◄── STABLE (per lane)│
│              │     │ - conversation       ◄── grows each turn  │
│ Output:      │     │                                           │
│ - lane ID    │     │ Output:                                   │
│              │     │ - response + tool calls                   │
└──────────────┘     └───────────────────────────────────────────┘
```

The router model:
- Receives only the user message + lane descriptions (small, stable prompt)
- Returns a lane ID
- Costs ~$0.001 per call on Haiku
- Has its own stable prefix (always the same prompt template)

The worker model:
- Receives the lane's canonical tool set (stable per lane)
- Gets full cache hits within the same lane across turns
- Only pays a cache miss when the lane changes

### Canonical Tool Serialisation

To guarantee byte-level prefix stability, tool schemas must be **canonicalised**:

```python
def canonicalise_tools(tools: list[Tool]) -> list[dict]:
    """Produce a deterministic, stable tool list for the API."""
    canonical = []
    for t in sorted(tools, key=lambda t: t.name):  # Stable sort by name
        canonical.append({
            "name": t.name,
            "description": t.description,  # Must be frozen/versioned
            "input_schema": _sort_schema(t.input_schema),  # Deterministic key order
        })
    return canonical


def _sort_schema(schema: dict) -> dict:
    """Recursively sort JSON schema keys for deterministic serialisation."""
    if isinstance(schema, dict):
        return {k: _sort_schema(v) for k, v in sorted(schema.items())}
    if isinstance(schema, list):
        return [_sort_schema(item) for item in schema]
    return schema
```

### What Must Never Be in Tool Schemas

| Volatile data | Why it breaks caching | Where to put it instead |
|---------------|----------------------|------------------------|
| Timestamps, dates | Changes every request | System prompt (after cache boundary) or user message |
| Rate limit counters | Changes between calls | Return as tool result metadata |
| Session/request IDs | Unique per request | User message or tool input at call time |
| Dynamic examples | May change with context | Static examples only, or omit |
| Server version strings | Changes on redeploy | Omit from description entirely |
| User-specific context | Per-user differences | System prompt (after cache boundary) |

## Worker Model Prompt Template

This template is designed so the **entire prefix up to `{conversation}`** stays identical across turns within a lane:

```
System prompt (STABLE — cached):
─────────────────────────────────────────────────
You are a helpful assistant. You have access to tools for interacting with
external systems. Use tools when the user's request requires it. Be concise.

When you need information you don't have, use the appropriate tool rather than
guessing. Report tool errors clearly.
─────────────────────────────────────────────────

Tools (STABLE per lane — cached):
─────────────────────────────────────────────────
[canonical tool schemas, sorted by name, frozen descriptions]
─────────────────────────────────────────────────
   ▲ cache_control: ephemeral (Anthropic)

Conversation (GROWS — not cached on first appearance):
─────────────────────────────────────────────────
[user messages, assistant responses, tool results]
─────────────────────────────────────────────────
```

With Anthropic, place `cache_control: {"type": "ephemeral"}` on:
1. The system prompt block
2. The last tool in the tool list

This ensures the entire system prompt + tools prefix is cached. The conversation history after the cache boundary is fresh input each turn (but grows incrementally, so the provider's automatic prefix matching may still cache the earlier conversation turns).

## Prompt Caching Preservation Checklist

### Prefix Stability (must be identical byte-for-byte across turns)

- [ ] **System prompt**: Static text, no interpolated variables (dates, session IDs, user names)
- [ ] **Tool list order**: Sort tools by `name` before sending to the API
- [ ] **Tool descriptions**: Frozen strings — no dynamic content (rate limits, counts, version strings)
- [ ] **Tool input schemas**: Deterministic key ordering (sort recursively)
- [ ] **Tool set composition**: Same tools in same order for all turns within a lane
- [ ] **Cache control markers**: Placed on system prompt and last tool (Anthropic)
- [ ] **No per-turn tool filtering**: Tool set changes only on lane switch, not every turn

### Data Placement (what goes where)

| Data | Placement | Rationale |
|------|-----------|-----------|
| System prompt | Cached prefix (position 1) | Static, identical every turn |
| Tool schemas | Cached prefix (position 2) | Static per lane |
| Lane selection metadata | Not sent to worker model | Router decides, worker just gets tools |
| Session-specific context | After cache boundary (in user message or late system block) | Volatile, changes per turn |
| Dynamic tool hints | Tool result from previous turn, or user message | Not in schema |
| Rate limits, quotas | Not in prompt at all | Return as tool result metadata |

### Tool Registry Rules

- [ ] **Version tool descriptions**: When updating a tool description, version it (`v2: ...`) so the change is intentional and tracked
- [ ] **Freeze schemas at startup**: Capture tool schemas once during MCP discovery, store in memory, reuse the same objects every turn
- [ ] **Never re-discover mid-session**: MCP tool discovery should happen once at startup, not per-turn
- [ ] **Validate stability**: Log a warning if `canonicalise_tools()` output differs from the previous turn's output (indicates a schema drift bug)
- [ ] **Test serialisation determinism**: Unit test that `canonicalise_tools(tools)` produces identical JSON bytes across multiple calls

### Lane Configuration Rules

- [ ] **Define lanes in config.json**: Not computed at runtime
- [ ] **Each lane is a fixed list of MCP server names**: Maps to all tools from those servers
- [ ] **Provide a `"full"` lane**: Fallback that includes all tools (safest default)
- [ ] **Lane switching is sticky**: Once a lane is selected, stay in it unless the user explicitly changes task type or the router detects a clear shift
- [ ] **Log lane switches**: Track cache invalidation events in metrics

## Provider-Specific Guidance

### Anthropic, Gemini, DeepSeek (90% cache discount)

All three providers offer 90% cache read discounts, making full-set caching nearly free:

- **Anthropic:** 1.25x write surcharge, semi-automatic (requires `cache_control` markers)
- **Gemini:** No write surcharge, automatic implicit caching (no API changes needed)
- **DeepSeek:** No write surcharge, fully automatic (prefix-based, min 64 tokens)

For all three: send all tools in canonical order, rely on caching. Tool search is disabled in `auto` mode.

### OpenAI (50-75% cache discount)

- Cache discount is weaker — even cached tokens are relatively expensive
- No write premium — cache misses are less punishing
- Tool search is enabled in `auto` mode — dynamically reduces schemas when threshold exceeded
- Caching is automatic — no markers needed, but prefix must still be byte-stable

### Decision Matrix (current implementation)

| Provider | Cache Discount | Strategy | Rationale |
|----------|---------------|----------|-----------|
| Anthropic | 90% | Send all tools + caching | Deep discount makes full-set caching nearly free |
| Gemini | 90% | Send all tools + caching | Same discount as Anthropic, no write surcharge |
| DeepSeek | 90% | Send all tools + caching | Same discount, fully automatic |
| OpenAI / other | 50-75% | Provider-aware tool search (`auto` mode) | Weaker discount makes full-set expensive; tool search reduces per-turn cost |

> **Note:** Lane routing (static tool groups) was evaluated and shelved. Tool search achieves the same token reduction without manual group configuration or false-negative risk from miscategorised tools. Tool search scales with tool count — its effectiveness depends on tool naming quality (distinctive names and descriptions), not on the number of tools.

## Relationship to Existing System

This design extends the current tool system ([DESIGN-tool-system.md](DESIGN-tool-system.md)) without changing the MCP protocol or tool proxy layer. Changes are confined to:

1. **Config**: New `ToolLanes` section in `config.json`
2. **Bootstrap**: Lane-aware tool grouping during startup
3. **Agent loop**: Lane selection before each `stream_chat` call
4. **Provider**: Already supports stable tool serialisation; may need `canonicalise_tools()`

The `McpToolProxy`, `McpManager`, `ToolResultFormatter`, and MCP servers are **unchanged**.

## Related

- [KV Cache and MCP Tool Routing Research](../research/kv-cache-and-mcp-tool-routing.md) — cost analysis backing this design
- [DESIGN: Tool System](DESIGN-tool-system.md) — current tool architecture
- [PLAN: Cost Reduction](../planning/PLAN-cost-reduction.md) — levers #1 (prompt caching) and #7 (tool schema optimisation)
- [PLAN: Cache-Preserving Tool Routing](../planning/PLAN-cache-preserving-tool-routing.md) — implementation plan
