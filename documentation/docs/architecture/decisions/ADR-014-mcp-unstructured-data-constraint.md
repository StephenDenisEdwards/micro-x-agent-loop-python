# ADR-014: MCP Returns Unstructured Text — Constraint on Compiled Mode

## Status

Open

## Context

The compiled mode architecture (described in [Cost-Aware Task Compilation for LLM Agents](../../research-papers/cost-aware-task-compilation-for-llm-agents/research-paper.md)) assumes that LLM-generated programs can process data programmatically: iterate over items, filter, score, rank, and write structured output. This requires structured input data — records with typed fields that code can index, compare, and manipulate.

MCP (Model Context Protocol) is the standard interface through which the agent accesses external services. The agent currently connects to both built-in tools and third-party MCP servers for Gmail, calendar, LinkedIn, and other data sources.

### The fundamental problem

**MCP servers return unstructured text content blocks.** This is by design — the MCP specification defines content blocks as text intended for LLM consumption, not programmatic processing. Third-party MCP servers follow this convention. We do not control their implementations and cannot require them to change.

This means:

1. A compiled mode program calls an MCP server (e.g., Gmail search)
2. It receives a text string — human-readable, unstructured, format varies by server
3. It cannot reliably parse this text into structured data for programmatic processing

This constraint undermines the core assumption of compiled mode. A generated program that receives text like:

```
ID: 18abc123
  Date: Thu, 27 Feb 2026 10:30:00 +0000
  From: jobs@jobserve.com
  Subject: New .NET roles
  Snippet: We found 5 new roles matching...
```

...cannot reliably extract fields, iterate over records, or perform deterministic operations on the data. The text format is not guaranteed, varies between servers, and may change without notice.

### This is not specific to our tools

Our built-in Gmail tools flatten API JSON responses to text before returning — but even if we changed them to return JSON, the problem remains for every third-party MCP server we integrate. The constraint is architectural: MCP is a text protocol designed for LLMs, not for programmatic data processing.

### Why this matters for the roadmap

The phased roadmap assumes:

- **Phase 3** (`agent_mcp` client library): bridge library for generated code to call MCP servers
- **Phase 4** (code generation and sandbox execution): LLM writes programs against MCP servers
- **Phase 5** (narrative callback): LLM returns for prose from compact results

Phase 4 is directly blocked by this constraint. If MCP servers return text, the generated program cannot perform structured data processing without additional interpretation.

### Options considered but not yet decided

**Option A: Per-item LLM interpretation within the generated program**

The generated code calls MCP, then calls the LLM to extract structured data from each text response. The pipeline becomes: MCP call → LLM extraction → structured processing → output.

- Pro: Works with any MCP server, no changes to the protocol
- Con: Compiled mode is no longer "deterministic execution" — it's "deterministic orchestration with per-item LLM calls." Cost savings still exist (N small calls vs 1 massive context) but the cost model and reliability guarantees change significantly
- Con: Each extraction call introduces potential for information loss or misinterpretation — the same problem ADR-013 identified for tool result summarization, now embedded in the execution pipeline

**Option B: Structured MCP server variants**

Build MCP server wrappers that return JSON in their text content blocks. Third-party servers get adapter layers that call the underlying server and structure the response.

- Pro: Generated code gets clean structured input
- Con: Requires building and maintaining adapters for every third-party server
- Con: Adapter must parse unstructured text from the underlying server — same fragility problem, just moved to a different layer

**Option C: Hybrid approach — use MCP for discovery, raw APIs for execution**

The agent uses MCP servers normally in prompt mode. In compiled mode, the generated program bypasses MCP and calls the underlying APIs directly (Gmail API, LinkedIn API, etc.) where structured responses are available.

- Pro: Clean structured data from APIs
- Con: Requires API credentials and client libraries for every service
- Con: Duplicates access paths — MCP for prompt mode, direct API for compiled mode
- Con: Not all services have accessible APIs (some are only available via MCP)

**Option D: Accept the constraint and limit compiled mode scope**

Compiled mode only applies to tasks where structured data is available — either from tools we control (built-in tools returning JSON) or from MCP servers that happen to return parseable structured content. For other data sources, prompt mode is used.

- Pro: No architectural changes, honest about limitations
- Con: Significantly reduces the applicability of compiled mode
- Con: The user doesn't know which tools return structured vs unstructured data

## Decision

None yet. This constraint requires further analysis before committing to an approach.

## Consequences

**Immediate:**

- Phase 3 (`agent_mcp` client library) can proceed — it's a bridge layer regardless of data format
- Phase 4 (code generation) is blocked until a data handling strategy is chosen
- The research paper's cost model assumes zero LLM cost for compiled execution, which is incorrect if Option A is adopted

**Questions to resolve:**

- What proportion of real-world compiled mode tasks depend on third-party MCP servers vs built-in tools we control?
- Is the per-item LLM extraction cost (Option A) low enough to preserve the cost advantage over prompt mode?
- Can the MCP specification evolve to support structured content types, or is text-only a permanent constraint?
- Is there a way to detect at runtime whether an MCP server's response is parseable as structured data, allowing automatic strategy selection?
