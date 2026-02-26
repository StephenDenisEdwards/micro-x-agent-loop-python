# ADR-013: Tool Result Summarization Is Fundamentally Unreliable

## Status

Accepted

## Context

ADR-012 introduced tool result summarization (Layer 3) as a cost reduction feature: large tool results are summarized by a cheaper model before the main model sees them. The intent was to reduce per-turn input tokens for tool-heavy workflows.

In practice, this caused a critical quality failure. A job search workflow using the standard config (summarization enabled) produced a report missing several job listings and their links compared to the same workflow using the baseline config (summarization disabled). The summarization model (Haiku) was discarding job listings it deemed less relevant — but all listings and links were required by the user.

### The fundamental problem

Tool result summarization is lossy by design. Neither the summarization model nor any heuristic can reliably determine which parts of a tool result will matter to the user's task. A URL buried in the middle of a web search result may be the entire point of the query. An LLM rewriting the result will sometimes drop it.

This is not a prompt engineering problem. No summarization prompt can reliably preserve "everything that matters" because what matters is determined by the user's intent, which the summarization model does not fully understand.

### Mechanical truncation has the same problem

OpenClaw (Claude Code's open-source codebase) uses mechanical truncation instead of LLM summarization: head+tail character retention, soft-trim/hard-clear escalation, newline-boundary cuts. This is cheaper and more predictable, but equally unreliable for information-dense, unstructured results. A web page with 20 job listings will lose the ones in the middle regardless of whether the truncation is mechanical or LLM-driven.

OpenClaw's approach works for its primary workload (source code files, command output) where important content is predictably located at the head or tail. It does not generalise to arbitrary web content, email bodies, document extracts, or other unstructured tool results that a general-purpose assistant must handle.

### What actually works

The only reliable approach is **not losing the data in the first place:**

1. **Better-scoped tools.** Tools should return structured, focused results rather than raw bulk. A job search tool that returns JSON records with every field preserved is reliable. A web fetch tool that dumps raw HTML into context is not.

2. **Write, don't remember.** The agent should write intermediate results to files as it processes them, rather than holding everything in context. Each tool result only needs to survive one turn — long enough to extract and persist what matters.

3. **Decompose.** Instead of "fetch 10 pages and compile a report" (which requires all 10 pages in context simultaneously), the workflow should be "fetch page 1, extract data, write to file, move on." Each step fits comfortably in context with nothing lost.

4. **Accept the context window as a hard constraint.** If a task requires more information than fits in context, the architecture must work around that — not pretend that summarization or truncation can compress it losslessly.

### Implications for "general personal agent"

This finding exposes a broader limitation. Current LLM agents — including OpenClaw/Claude Code — work well for **bounded tasks** where relevant information fits in context: editing a specific file, analysing a document, answering questions about a known codebase.

They do not reliably handle **open-ended tasks** that require processing more information than fits in context: comprehensive web research, multi-source data aggregation, anything where completeness matters. No amount of context management sophistication changes this — the context window is finite and every management strategy is lossy.

The honest architecture for a general assistant is: **reliable tools for reliable data handling, LLM for judgement and synthesis, with a clear boundary between the two.** The agent orchestrates and interprets; it does not buffer and compress.

## Decision

1. **Do not recommend tool result summarization for general-purpose use.** It remains available as an opt-in feature for workloads where partial information loss is acceptable (e.g., large log file analysis where the gist suffices). It is disabled in the recommended config.

2. **Create `config-standard-no-summarization.json`** as the recommended config for general assistant use — all cost savings except tool result summarization.

3. **Retain `config-standard.json`** (with summarization enabled) for users who explicitly accept the tradeoff for cost-sensitive, loss-tolerant workloads.

4. **Document the limitation clearly** in the config reference so users understand the tradeoff without needing to discover it empirically.

5. **Future tool design should favour structured, focused output** over raw bulk. When building or integrating tools, prefer returning exactly the data the agent needs rather than relying on post-hoc compression.

## Consequences

**Easier:**

- Users get reliable output by default without understanding context management internals
- Tool design decisions are guided by a clear principle: return structured data, not raw bulk
- The failure mode is documented and the workaround (disable summarization) is simple

**Harder:**

- Cost reduction for tool-heavy workflows is limited to the other four layers (prompt caching, cheaper compaction model, smart compaction trigger, concise output)
- Workflows that process many large tool results will consume more tokens per session

**Open questions:**

- Whether a hybrid approach could work: summarize old tool results during compaction (when they're already stale) but never summarize the current turn's results. This preserves data when it matters most (the turn it arrives) while still reducing context growth over time.
- Whether tool-specific structured extraction (rejected in ADR-012 as too much per-tool work) should be reconsidered for high-value tools like web search and email.
