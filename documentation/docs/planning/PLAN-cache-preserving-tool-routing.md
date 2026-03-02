# Plan: Cache-Preserving MCP Tool Routing

## Status

**Planned**

## Context

The agent sends all ~60-120 MCP tool schemas on every API call. Prompt caching makes this affordable today, but as the tool set grows, per-turn schema overhead becomes significant — especially on OpenAI where cached tokens still cost 25-50% of full price.

"Smart routing" (sending different tool subsets per turn) seems like the obvious fix, but it **breaks prompt caching** by changing the prefix. With Anthropic's 1.25x cache-write penalty, naive per-turn routing can cost *more* than sending all tools.

This plan implements **lane-based routing** — a small number of fixed tool groups that preserve prefix stability within each lane. See [DESIGN-cache-preserving-tool-routing.md](../design/DESIGN-cache-preserving-tool-routing.md) for the full architecture.

## Prerequisites

- [Cost Metrics Logging](PLAN-cost-metrics-logging.md) — **Completed** — needed to measure cache hit rates and validate savings
- [Cost Reduction Phase 1](PLAN-cost-reduction.md) — **Completed** — prompt caching must be enabled first

## Phases

### Phase 1: Canonical Tool Serialisation (cache stability guarantee)

**Goal:** Ensure the tool prefix is byte-stable across turns, even without routing. This is a prerequisite — it fixes potential cache instability before adding routing complexity.

**Why first:** Today, tool schemas are serialised in MCP discovery order, which depends on server startup timing. If a server restarts or tools are discovered in a different order, the prefix silently changes and cache breaks. Phase 1 eliminates this risk.

### Phase 2: Static Lane Configuration + Deterministic Router

**Goal:** Define tool lanes in config, implement keyword-based lane selection, wire through the agent loop.

### Phase 3: LLM-Based Router for Ambiguous Cases (Optional)

**Goal:** Add a cheap Haiku classifier for messages that don't match any keyword pattern. Only if Phase 2's deterministic router proves insufficient.

---

## Implementation Plan

### Phase 1: Canonical Tool Serialisation

#### Step 1: Add `canonicalise_tools()` utility

**File:** `src/micro_x_agent_loop/tool.py` (new function, not a class)

```python
def canonicalise_tools(tools: list[Tool]) -> list[dict]:
    """Produce a deterministic, stable tool list for the API.

    Sorts tools by name and recursively sorts schema keys to ensure
    byte-identical serialisation across calls.
    """
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": _sort_schema(t.input_schema),
        }
        for t in sorted(tools, key=lambda t: t.name)
    ]


def _sort_schema(schema: dict | list | Any) -> dict | list | Any:
    if isinstance(schema, dict):
        return {k: _sort_schema(v) for k, v in sorted(schema.items())}
    if isinstance(schema, list):
        return [_sort_schema(item) for item in schema]
    return schema
```

#### Step 2: Use canonical serialisation in providers

**Files:** `providers/anthropic_provider.py`, `providers/openai_provider.py`

Replace `convert_tools()` with a call to `canonicalise_tools()`. The Anthropic provider's `cache_control` marker goes on the last item of the already-sorted list.

#### Step 3: Add stability assertion

**File:** `src/micro_x_agent_loop/agent.py`

On the second and subsequent turns, compare the serialised tool list to the previous turn's. Log a warning if they differ (indicates a schema drift bug — shouldn't happen after canonicalisation).

```python
import json

# In agent __init__:
self._prev_tool_json: str | None = None

# Before each API call:
tool_json = json.dumps(canonical_tools, separators=(",", ":"))
if self._prev_tool_json is not None and tool_json != self._prev_tool_json:
    logger.warning("Tool schema changed between turns — prefix cache invalidated")
self._prev_tool_json = tool_json
```

#### Step 4: Tests

**File:** `tests/test_tool_canonicalisation.py`

- `canonicalise_tools()` produces identical output regardless of input order
- `_sort_schema()` handles nested dicts, lists, primitives
- Serialised JSON is byte-identical across multiple calls
- Provider `convert_tools()` uses canonical ordering

### Phase 2: Static Lanes + Deterministic Router

#### Step 5: Add lane configuration to config schema

**File:** `src/micro_x_agent_loop/app_config.py`

```python
@dataclass
class ToolLane:
    name: str
    servers: list[str]  # MCP server names to include
    keywords: list[str]  # Trigger keywords for deterministic routing

# In AppConfig:
tool_lanes: list[ToolLane]  # Parsed from config.json "ToolLanes"
default_lane: str  # "full" — fallback lane
```

**Config format:**

```json
{
  "ToolLanes": {
    "coding": {
      "servers": ["filesystem", "codegen", "github"],
      "keywords": ["write", "code", "implement", "fix", "bug", "refactor", "file", "test"]
    },
    "research": {
      "servers": ["web", "google", "linkedin"],
      "keywords": ["search", "find", "look up", "research", "articles"]
    },
    "comms": {
      "servers": ["whatsapp", "google"],
      "keywords": ["email", "gmail", "whatsapp", "message", "send", "calendar"]
    }
  },
  "DefaultLane": "full"
}
```

The `"full"` lane is implicit — always exists, includes all tools.

#### Step 6: Add lane router

**File:** `src/micro_x_agent_loop/lane_router.py` (new)

Pure function, no async, no provider dependency:

- `select_lane(user_message, current_lane, lanes) -> str` — keyword matching with sticky behaviour
- `/lane <name>` command for explicit override
- Returns lane ID (config key or `"full"`)

#### Step 7: Build lane tool registries at startup

**File:** `src/micro_x_agent_loop/bootstrap.py`

After MCP discovery, group tools by server name into lane-specific lists. Pre-canonicalise each lane's tool list and store as frozen data:

```python
lane_tools: dict[str, list[dict]] = {}
for lane in app.tool_lanes:
    lane_tools[lane.name] = canonicalise_tools(
        [t for t in all_tools if t.server_name in lane.servers]
    )
lane_tools["full"] = canonicalise_tools(all_tools)
```

#### Step 8: Wire lane selection into the agent loop

**File:** `src/micro_x_agent_loop/agent.py`

Before each `stream_chat()` call:
1. Call `select_lane()` to get the lane ID
2. Look up the pre-built canonical tool list for that lane
3. Pass it to `stream_chat()`
4. Track lane switches in metrics (cache invalidation event)

#### Step 9: Add `/lane` command

**File:** `src/micro_x_agent_loop/agent.py` (in command handling)

- `/lane` — show current lane and available lanes
- `/lane <name>` — switch to a specific lane
- `/lane full` — switch to all tools (default)

#### Step 10: Tests

**File:** `tests/test_lane_router.py`

- Keyword matching selects correct lane
- Sticky behaviour: stays in current lane when no keywords match
- `/lane` override works
- Unknown lane falls back to `"full"`
- Lane with no matching tools returns empty list (edge case)

### Phase 3: LLM Router (Optional)

#### Step 11: Add LLM classification for ambiguous messages

**File:** `src/micro_x_agent_loop/lane_router.py`

- `build_router_prompt(user_message, lane_names) -> str` — stable prompt template
- `parse_router_response(response_text, lane_names) -> str` — extract lane ID
- Called from `agent.py` when `select_lane()` returns `"full"` and `llm_routing_enabled` is configured

Uses the same pattern as mode selection Phase 2 (Haiku call, ~$0.001, pure function + async caller in agent.py).

#### Step 12: Config and wiring

- `LlmRoutingEnabled: bool` (default `false`)
- `LlmRoutingModel: str` (default `""` = use compaction model or Haiku)

---

## Files Modified

| File | Phase | Change |
|------|-------|--------|
| `src/micro_x_agent_loop/tool.py` | 1 | Add `canonicalise_tools()`, `_sort_schema()` |
| `src/micro_x_agent_loop/providers/anthropic_provider.py` | 1 | Use `canonicalise_tools()` in `convert_tools()` |
| `src/micro_x_agent_loop/providers/openai_provider.py` | 1 | Use `canonicalise_tools()` in `convert_tools()` |
| `src/micro_x_agent_loop/agent.py` | 1, 2 | Stability assertion; lane selection before API calls; `/lane` command |
| `src/micro_x_agent_loop/app_config.py` | 2 | `ToolLane` dataclass, parsing |
| `src/micro_x_agent_loop/bootstrap.py` | 2 | Pre-build lane tool registries |
| `src/micro_x_agent_loop/lane_router.py` | 2, 3 | New file: `select_lane()`, optional LLM router |
| `tests/test_tool_canonicalisation.py` | 1 | New file: canonicalisation tests |
| `tests/test_lane_router.py` | 2 | New file: routing tests |

## Verification

### Phase 1

1. Run existing tests — no regressions from canonicalisation
2. Start agent, run two turns, check logs: no "Tool schema changed" warning
3. Verify `cache_read_input_tokens > 0` on turn 2 (prompt caching working)
4. Restart an MCP server mid-session, verify tools re-canonicalise to same order

### Phase 2

1. Start agent with `ToolLanes` configured
2. Send a coding message → verify only coding tools in API call (check debug log: `tools=N`)
3. Send a follow-up coding message → verify same lane, cache hit (check `cache_read_input_tokens`)
4. Send `/lane research` → verify lane switch, new tool set
5. Send a research message → verify cache hit within research lane
6. Send `/lane full` → verify all tools returned

### Phase 3

1. Send an ambiguous message → verify Haiku classification call in logs
2. Verify classification cost ~$0.001
3. Verify classified lane gets cache hits on subsequent turns

## Cost Impact

### Current state (all tools, with caching)

Per 10-turn session on Anthropic with ~12,700 token prefix:
- Turn 1 cache write: $0.016
- Turns 2-10 cache read: $0.011
- **Total prefix cost: $0.027**

### With lane routing (assuming 3,200 token lane prefix)

Assuming one lane switch mid-session:
- Lane 1 turns 1-5: write $0.004 + reads $0.001 = $0.005
- Lane 2 turns 6-10: write $0.004 + reads $0.001 = $0.005
- **Total prefix cost: $0.010** — saves $0.017 (63%)

On OpenAI gpt-4.1: saves $0.052 per session (63%).

### Break-even analysis

Lane routing loses money only if lanes switch **every turn** on Anthropic (cache write penalty exceeds savings). With sticky lane behaviour, this doesn't happen in practice.

## Related

- [DESIGN: Cache-Preserving Tool Routing](../design/DESIGN-cache-preserving-tool-routing.md) — architecture and rationale
- [KV Cache and MCP Tool Routing Research](../research/kv-cache-and-mcp-tool-routing.md) — cost modelling
- [PLAN: Cost Reduction](PLAN-cost-reduction.md) — levers #1 and #7
- [DESIGN: Tool System](../design/DESIGN-tool-system.md) — current tool architecture
