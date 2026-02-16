# Token Compaction: OpenClaw Comparison

Analyzed Feb 2026 after implementing our token budget compaction (ADR-005).

## Our Approach (single-pass threshold)

- Trigger: `input_tokens > InputTokenBudget` (from API response usage)
- Action: truncate old tool results to `ToolResultRetentionChars` (first N chars only)
- Keeps most recent tool-result message intact
- Idempotent, no extra API calls, 2 config settings

## OpenClaw's Approach (multi-layer)

Source: `C:\Users\steph\source\repos\openclaw`

### Layer 1 — Tool result truncation at creation
- `src/agents/pi-embedded-runner/tool-result-truncation.ts`
- Caps each result at 30% of context window, hard max 400K chars
- Breaks at newline boundaries (smarter cut points)

### Layer 2 — Session persistence guard
- `src/agents/session-tool-result-guard.ts`
- Truncates anything over 400K chars before writing to session file
- Prevents oversized results from poisoning future session loads

### Layer 3 — In-memory context pruning (most relevant to us)
- `src/agents/pi-extensions/context-pruning/pruner.ts`
- **Soft-trim**: tool results >4K chars → keep 1500 head + 1500 tail chars
- **Hard-clear**: if context >50% window after soft-trim → replace entire old results with placeholder
- Protects last 3 assistant messages (we protect last 1 tool-result message)
- Uses TTL (5m) for Anthropic prompt caching optimization
- Does NOT modify session file (in-memory only)

### Layer 4 — Overflow fallback
- `src/agents/pi-embedded-runner/compact.ts`
- Triggers when API call fails with context overflow error
- LLM-powered multi-stage summarization (extra API calls)
- `src/agents/compaction.ts` — chunked summarization with progressive fallback

## Ideas Worth Stealing

1. **Head + tail retention** — keeping the end of tool output too (last rows of a table, final status). Our current approach only keeps the beginning.
2. **Soft-trim / hard-clear escalation** — two severity levels instead of one-shot truncation.
3. **Newline-boundary cuts** — avoid truncating mid-line for cleaner retained content.
4. **Protect more messages** — OpenClaw protects last 3 assistant turns; we only protect the most recent tool-result message.

## Key Config (OpenClaw defaults)
```
softTrimRatio: 0.3      # start soft-trim at 30% of context
hardClearRatio: 0.5      # start hard-clear at 50%
minPrunableToolChars: 50000
softTrim: { maxChars: 4000, headChars: 1500, tailChars: 1500 }
hardClear: { placeholder: "[Old tool result content cleared]" }
keepLastAssistants: 3
ttl: "5m"
```

## Key Files in OpenClaw
- `src/agents/compaction.ts` — history compaction and summarization
- `src/agents/context-window-guard.ts` — context limits, validation
- `src/agents/pi-embedded-runner/tool-result-truncation.ts` — creation-time truncation
- `src/agents/pi-extensions/context-pruning/pruner.ts` — in-memory pruning
- `src/agents/session-tool-result-guard.ts` — persistence guard
- `src/agents/usage.ts` — token usage normalization
- `docs/concepts/compaction.md` — compaction overview
- `docs/concepts/session-pruning.md` — pruning details
