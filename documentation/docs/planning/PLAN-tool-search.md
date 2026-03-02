# Plan: Tool Search (On-Demand Tool Discovery)

## Status

Completed

## Context

All ~60+ MCP tool schemas are sent to every LLM API call. With OpenAI's weak cache discount (50-75%), this is expensive for trivial tasks. Claude Code solves this with "MCP Tool Search" — when tool definitions exceed 10% of the context window, it defers schemas and provides a search tool so the LLM loads tools on demand.

This plan implements the same approach for our agent. See [KV Cache and MCP Tool Routing](../research/kv-cache-and-mcp-tool-routing.md) for the full cost analysis and [PLAN-cost-reduction.md](PLAN-cost-reduction.md) lever #7.

## Design

When tool schemas exceed a configurable threshold, replace them with a single `tool_search` built-in tool. The LLM searches for tools by keyword, matched tools get their full schemas injected into the next API call within the same turn.

**Key rule:** `_tool_map` (used for execution) always contains ALL tools. Only the schemas sent to the LLM are filtered.

## Files to Create

### `src/micro_x_agent_loop/tool_search.py` (new)

Core module containing:

- `estimate_tool_schema_tokens(converted_tools)` — tiktoken-based token count of all tool schemas
- `should_activate_tool_search(setting, converted_tools, model, threshold_percent)` — returns bool. Handles `"false"`, `"true"`, `"auto"`, `"auto:N"` settings
- `TOOL_SEARCH_SCHEMA` — the tool_search tool definition (name, description, input_schema with `query` param)
- `_CONTEXT_WINDOWS` — dict mapping model prefixes to context window sizes
- `ToolSearchManager` class:
  - `__init__(all_tools, converted_tools)` — builds name->(Tool, converted_dict) index
  - `begin_turn()` — clears loaded tools (called at start of each TurnEngine.run())
  - `get_tools_for_api_call()` — returns `[TOOL_SEARCH_SCHEMA] + loaded tool schemas`
  - `handle_tool_search(query)` — keyword search across tool names/descriptions, marks matches as loaded, returns formatted results text
  - `is_tool_search_call(tool_name)` — returns `tool_name == "tool_search"`

Search algorithm: split query into terms, score each tool (name match = 3pts, description match = 1pt), return top 20 sorted by score. Loaded tools persist for the entire turn.

### `tests/test_tool_search.py` (new)

Unit tests for activation logic, search matching, tool loading, turn reset.

## Files to Modify

### `src/micro_x_agent_loop/app_config.py`

Add to `AppConfig` (in cost reduction section):
```python
tool_search_enabled: str  # "false" | "true" | "auto" | "auto:N"
```

Add to `parse_app_config()`:
```python
tool_search_enabled=str(config.get("ToolSearchEnabled", "false")).strip().lower(),
```

### `src/micro_x_agent_loop/agent_config.py`

Add field:
```python
tool_search_enabled: str = "false"
```

### `src/micro_x_agent_loop/bootstrap.py`

Pass through in `AgentConfig(...)` constructor:
```python
tool_search_enabled=app.tool_search_enabled,
```

### `src/micro_x_agent_loop/system_prompt.py`

Add `_TOOL_SEARCH_DIRECTIVE` constant — guidance telling LLM to search before calling unknown tools. Add `tool_search_active: bool = False` parameter to `get_system_prompt()`, append directive when active.

### `src/micro_x_agent_loop/agent.py`

In `__init__` (after `self._converted_tools` assignment):
1. Call `should_activate_tool_search()` to determine if active
2. Create `ToolSearchManager` if active
3. Append tool search directive to `self._system_prompt`
4. Pass `tool_search_manager` to `TurnEngine` constructor

In `_print_tool_list()`: show tool search status when active.

### `src/micro_x_agent_loop/turn_engine.py`

In `__init__`: accept `tool_search_manager: ToolSearchManager | None = None`.

In `run()` method — the main changes:
1. Call `begin_turn()` at start
2. Replace `self._converted_tools` with `tool_search_manager.get_tools_for_api_call()` when active
3. After LLM response, separate `tool_search` calls from regular tool calls
4. Handle `tool_search` calls inline (no MCP execution) — call `handle_tool_search(query)`, build tool_result message
5. Execute regular tool calls normally via existing `execute_tools()`
6. Combine all results in original order, append to messages, continue loop

In `_record_api_payload`: pass actual `len(api_tools)` instead of `len(self._converted_tools)`.

## Data Flow (when tool search is active)

```
Turn starts -> begin_turn() clears loaded tools
  |
  v
API call 1: tools = [tool_search]
  LLM returns: tool_use "tool_search" query="read file"
  -> handle_tool_search("read file") loads filesystem__read_file etc.
  -> result appended to messages
  |
  v
API call 2: tools = [tool_search, filesystem__read_file, filesystem__bash, ...]
  LLM returns: tool_use "filesystem__read_file" path="foo.py"
  -> execute via _tool_map["filesystem__read_file"] (always has everything)
  -> result appended to messages
  |
  v
API call 3: tools = [tool_search, filesystem__read_file, filesystem__bash, ...]
  LLM returns: end_turn with text response
  -> done
```

## Config

```json
{
  "ToolSearchEnabled": "auto"
}
```

Values: `"false"` (default, no change to current behavior), `"true"` (always on), `"auto"` (activate when tool schemas exceed 40% of context window), `"auto:N"` (custom threshold percentage).

## Prompt Caching Impact

When tool search is active:
- **Stable prefix**: system prompt + `tool_search` schema (always position [0]) — this caches well
- **Variable suffix**: loaded tool schemas vary per API call within a turn — won't cache across turns
- **Net effect**: instead of caching ~12,700 tokens (all tools), we cache ~500 tokens (search tool only), but total tokens sent per call drops dramatically

## Verification

1. Run with `"ToolSearchEnabled": "false"` — verify no behavior change (all tools sent as before)
2. Run with `"ToolSearchEnabled": "true"` — verify tool_search tool appears, LLM can discover and call tools
3. Run with `"ToolSearchEnabled": "auto"` with many tools — verify it activates when threshold exceeded
4. Check `/tool` command shows tool search status
5. Check `/debug show-api-payload` shows correct tools_count (1 + loaded, not all 60+)
6. Check `/cost` metrics track tool_search calls
7. Run existing tests — no regressions
