# ADR-014: Structured Tool Results with Configurable LLM Formatting

## Status

**Accepted** (2026-03-12) — Option C implemented incrementally. Supersedes the original "Open" status.

## Revision History

- **v1** — Original: "MCP Returns Unstructured Text" (flawed premise attributing constraint to MCP protocol)
- **v2** — Corrected: "Tool Results Are Unstructured Text — Design Choice" (ISSUE-001 correction)
- **v3** — Current: "Structured Tool Results with Configurable LLM Formatting" (reflects implemented solution)

See [ISSUE-001](../../issues/ISSUE-001-adr-014-flawed-premise.md) for the v1→v2 correction record.

## Context

The compiled mode architecture (described in [Cost-Aware Task Compilation for LLM Agents](../../research-papers/cost-aware-task-compilation-for-llm-agents/research-paper.md)) requires structured input data for programmatic processing — records with typed fields that code can index, compare, and manipulate.

When this ADR was originally written (v1/v2), all tools returned human-readable text strings. Built-in Python tools (Gmail, GitHub, etc.) flattened structured API responses to prose, and `McpToolProxy` extracted `.text` from MCP content blocks and joined with newlines, discarding any JSON structure.

Since then, the codebase has evolved significantly:

1. **All tools migrated to TypeScript MCP servers** — no Python built-in tools remain (only pseudo-tools: `ask_user`, `tool_search`)
2. **`ToolResult` dataclass** introduced with both `text` and `structured` fields
3. **`McpToolProxy`** updated to preserve `structuredContent` from MCP responses
4. **`ToolResultFormatter`** created with config-driven per-tool formatting strategies
5. **MCP `structuredContent`** support added to our TypeScript MCP servers

These changes collectively implement Option C from the original options analysis.

## Decision

**Option C: Structured data from our tools + configurable formatting + fallback for unstructured responses.**

This was implemented incrementally rather than as a single decision, but the architecture is now in place.

## Implementation (as built)

### Data flow

```
MCP Server → structuredContent + text
    ↓
McpToolProxy.execute() → ToolResult(text, structured, is_error)
    ↓
ToolResultFormatter.format(tool_name, text, structured)
    ↓
Formatted text for LLM context window
```

### Key components

**`ToolResult`** (`tool.py`):
```python
@dataclass
class ToolResult:
    text: str                              # Human-readable fallback
    structured: dict[str, Any] | None = None  # Machine-parseable JSON
    is_error: bool = False
```

**`McpToolProxy`** (`mcp/mcp_tool_proxy.py`):
- Extracts `.text` from `TextContent` blocks (human-readable fallback)
- Extracts `structuredContent` if present (machine-parseable data)
- Returns both in `ToolResult`

**`ToolResultFormatter`** (`tool_result_formatter.py`):
- Config-driven per-tool formatting via `ToolFormatting` config section
- Four strategies: `json` (default), `table`, `text`, `key_value`
- Falls back to `ToolResult.text` when no `structuredContent` is present
- Examples: `gmail_search` → table format, `github__get_pr` → json, `filesystem__bash` → text (stdout field)

### What this enables

- **Prompt mode**: Structured data is formatted contextually for the LLM (tables, key-value, JSON) — better than raw text dumps
- **Compiled mode** (future): Programs can access `ToolResult.structured` directly for programmatic processing
- **Cost reduction**: Configurable formatting can reduce token count (e.g., table format vs verbose JSON)

### Remaining gap

- **Compiled mode execution** (Phase 4) has not been attempted yet, but the data pipeline now supports it
- **Third-party MCP servers** that don't provide `structuredContent` fall back to `.text` — LLM extraction (Option B) is available as a future enhancement if needed but has not been implemented
- **Not all MCP servers may populate `structuredContent`** — the fallback to `.text` handles this gracefully

## Consequences

- Phase 3 (`agent_mcp` client library) and Phase 4 (code generation) are **no longer blocked** by data format — structured data is available via `ToolResult.structured`
- The `ToolResultFormatter` adds a small amount of complexity but provides significant flexibility in how tool results are presented to the LLM
- Per-tool formatting configuration in `config.json` means formatting can be tuned without code changes
- The original "questions to resolve" from v2 are now largely moot:
  - All production tools are our own MCP servers (no third-party dependency for core workflows)
  - Tool return format change did not need a separate ADR — it was a natural evolution of the Tool protocol
