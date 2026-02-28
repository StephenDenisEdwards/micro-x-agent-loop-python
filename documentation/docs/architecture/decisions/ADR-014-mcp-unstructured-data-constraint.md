# ADR-014: Tool Results Are Unstructured Text — Design Choice Affecting Compiled Mode

## Status

Open

## Correction Notice

The original version of this ADR incorrectly attributed the unstructured data problem to the MCP protocol specification. MCP is a JSON-RPC protocol and **can return structured JSON** in text content blocks. The constraint is self-imposed by our tool implementations and proxy layer, not by the protocol. See [ISSUE-001](../../issues/ISSUE-001-adr-014-flawed-premise.md) for the full correction record.

## Context

The compiled mode architecture (described in [Cost-Aware Task Compilation for LLM Agents](../../research-papers/cost-aware-task-compilation-for-llm-agents/research-paper.md)) assumes that LLM-generated programs can process data programmatically: iterate over items, filter, score, rank, and write structured output. This requires structured input data — records with typed fields that code can index, compare, and manipulate.

The agent accesses external services through both built-in tools and MCP servers. Currently, **all tools return human-readable text strings** rather than structured JSON. This is a design choice in our code, not a protocol limitation.

### The actual problem

**Our tool implementations flatten structured data to human-readable text before returning.**

1. **Built-in tools** (Gmail, GitHub, etc.) receive structured JSON from their underlying APIs but format it as human-readable text. For example, `GmailSearchTool.execute()` receives JSON from the Gmail API and returns `f"ID: {msg['id']}\n  Date: {date}\n..."`.

2. **`McpToolProxy`** extracts `.text` from MCP content blocks and joins with newlines, discarding any JSON structure that may be present in the response.

3. **Third-party MCP servers** may return JSON or prose in their text content blocks — we don't control this per server, but the protocol supports both.

This means a compiled mode program receiving tool results gets text like:

```
ID: 18abc123
  Date: Thu, 27 Feb 2026 10:30:00 +0000
  From: jobs@jobserve.com
  Subject: New .NET roles
  Snippet: We found 5 new roles matching...
```

...instead of parseable JSON. The program cannot reliably extract fields, iterate over records, or perform deterministic operations on this text.

### What is tractable

Since the constraint is in our code, not the protocol:

- **Built-in tools** can be changed to return JSON strings. The Gmail API already returns JSON — we just need to stop flattening it.
- **Our own MCP servers** can return JSON in their text content blocks. This is valid MCP.
- **`McpToolProxy`** can be updated to detect and preserve JSON responses.
- **Third-party MCP servers** are the only true unknown — some return JSON, some return prose, and we don't control this.

### Why this matters for the roadmap

The phased roadmap assumes:

- **Phase 3** (`agent_mcp` client library): bridge library for generated code to call MCP servers
- **Phase 4** (code generation and sandbox execution): LLM writes programs against MCP servers
- **Phase 5** (narrative callback): LLM returns for prose from compact results

Phase 4 requires structured data for programmatic processing. This is achievable for tools we control. For third-party MCP servers returning prose, a fallback strategy is needed.

### Options

**Option A: Change our tools to return JSON**

Built-in tools return JSON strings. `McpToolProxy` passes through content block text as-is (which may be JSON from well-designed MCP servers). The agent formats JSON as human-readable text only when injecting into prompt mode context.

- Pro: Fixes the problem at source for all tools we control
- Pro: No protocol changes needed — JSON in text content blocks is valid MCP
- Pro: Compiled mode programs get structured input from our tools
- Con: Third-party MCP servers that return prose still need handling

**Option B: Per-item LLM interpretation as fallback**

For tool results that are not valid JSON, the generated program calls the LLM to extract structured data. Only needed for third-party MCP servers that return prose.

- Pro: Works with any MCP server regardless of response format
- Con: Adds per-item LLM cost for non-JSON responses
- Con: Potential for information loss in extraction

**Option C: Combine A and B**

Return JSON from our tools (Option A). For third-party MCP servers, attempt `json.loads()` on the response — if it parses, use structured data; if not, fall back to LLM extraction (Option B).

- Pro: Best of both — structured when available, graceful fallback when not
- Pro: No changes needed to third-party servers
- Con: Slightly more complex pipeline

## Decision

None yet. Option C (our tools return JSON + auto-detect + LLM fallback) is the most promising direction but requires further analysis.

## Consequences

**Immediate:**

- Phase 3 (`agent_mcp` client library) can proceed — it's a bridge layer regardless of data format
- Phase 4 (code generation) is not blocked by the MCP protocol but requires a data handling strategy for mixed structured/unstructured responses
- The research paper's cost model for compiled mode remains valid for tools returning JSON; a cost adjustment is needed only for the LLM extraction fallback path

**Questions to resolve:**

- What proportion of real-world compiled mode tasks depend on third-party MCP servers vs tools we control?
- For third-party servers, what proportion return JSON vs prose?
- Should the tool return format change be a separate ADR given it affects prompt mode context injection?
