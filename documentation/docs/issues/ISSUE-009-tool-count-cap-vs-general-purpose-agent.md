# ISSUE-009: Tool-count caps vs a general-purpose agent

## Date

2026-06-01

## Status

**Open.** Tactical mitigation shipped (per-profile server disable + Groq Scout
profile trimmed under the cap). The durable architectural fix (cap-aware tool
management + recover-on-miss tool search) is not yet built.

## Summary

A general-purpose agent wants **many** tools available (this project ships
~131: ~125 MCP/native + ~6 pseudo-tools). But there is no universal "send all
tools" — every provider imposes a ceiling, and model quality degrades long
before the hard limit:

1. **Hard provider caps.** Groq rejects any request with **> 128 tools**
   (`400 'tools': maximum number of items is 128`). Other providers have their
   own limits or undocumented degradation points.
2. **Soft quality cap.** Even when a provider *accepts* a large tool list,
   models mis-select, hallucinate tool names, and waste context as the list
   grows. Our own findings: Gemma 3 4B degrades past ~15 tools
   ([PLAN-gemma-model-support](../planning/PLAN-gemma-model-support.md)); a 7B
   model guesses parameters instead of reading schemas
   (research/[local-model-hardware-options](../research/local-model-hardware-options.md)).

So "many tools" and "reliable tool calling" are in direct tension on **every**
provider. Anthropic hides it (lenient validation + 200k context); Groq surfaces
it as a hard 400.

## Why this isn't a quick fix

The obvious answer — **tool retrieval / search** (send a relevant handful, not
all 131) — already exists here as `tool_search`, but it failed on Groq for two
compounding reasons:

1. **`tool_search` is a *prompted* protocol, not *enforced*.** It asks the model
   to call `tool_search` first to *discover* a tool, which is then added to the
   request's tool list and can be called on the next iteration. A compliant
   model does this; a smaller model (Llama 4 Scout) — especially when the user
   prompt *names the exact tool* ("run the codegen … task") — skips discovery
   and calls the tool directly at iteration 0, when it is **not** in
   `request.tools`.
2. **Groq strict-validates tool calls server-side.** A call to a tool not in the
   request is rejected outright:
   `tool call validation failed: attempted to call tool 'codegen__run_task'
   which was not in request.tools`. On Anthropic the same model behaviour is
   recoverable (the loop sees an unknown-tool result and can retry); on Groq it
   is a fatal 400.

This boxes a 131-tool agent into a corner on Groq:
- **send all tools** → hits the 128 cap, and
- **tool search** → model calls an undiscovered tool → strict-validation 400.

A one-line config can't resolve a contradiction between two provider rules; the
real fix is an orchestration layer that is provider-cap-aware and recovers from
discovery misses.

## Options considered

### Option A — Per-profile server disable (tactical, shipped)
Let a Base-inheriting profile switch off heavy MCP servers it doesn't need, so
the tool count drops under the cap. Implemented: `McpManager._is_disabled`
skips a server whose config a profile overrides with `false`/`null`/
`{"enabled": false}` (deep-merge can override a key but not delete a Base
entry). `config-standard-groq-scout.json` disables discord/playwright/
interview-assist/whatsapp → ~60 tools, well under 128.

- **Pros:** Simple, explicit, no model cooperation needed, works today. Also a
  quality win (smaller, more relevant tool set).
- **Cons:** Manual and per-profile. Doesn't scale — adding servers can silently
  re-breach the cap. Removes capability wholesale rather than per-task.

### Option B — Cap-aware automatic trimming
The tool-management layer knows each provider's cap and never sends more than
(cap − margin) tools: auto-activate `tool_search` when the count exceeds the
cap, or drop lowest-priority tools.

- **Pros:** Automatic; no profile maintenance; provider-portable.
- **Cons:** Still depends on tool_search working (Option C) when it trims via
  search; "which tools to drop" needs a priority signal.

### Option C — Recover-on-miss tool search (durable core fix)
Make tool search robust to a non-compliant model: when the model calls a tool
that exists but isn't loaded, the orchestrator **auto-loads it and retries**
instead of forwarding an invalid request. On Groq this means catching the
400 (or pre-validating against the full registry before the call) and
re-issuing with the tool added.

- **Pros:** Fixes the root fragility; makes tool_search viable on strict
  providers; keeps the small-tool-list quality benefit.
- **Cons:** More moving parts; needs pre-call validation or 400-parse + retry;
  must bound retries to avoid loops.

### Option D — Accept provider-specific reality
Document that strict/low-cap providers (Groq) need trimmed profiles; keep the
full tool set only for lenient/high-cap providers (Anthropic).

- **Pros:** No code; honest about the trade-off.
- **Cons:** Undermines "general-purpose across providers"; pushes the problem
  onto every user.

## Recommendation

**A now (done), then C, with B layered on top.** A unblocks Groq today. C is the
highest-leverage durable change — it makes tool search actually dependable on
strict providers, which is the real blocker. B then makes trimming automatic and
cap-aware so adding servers can't silently re-breach a provider limit.

## Acceptance criteria

- Tool count sent to any provider never exceeds its cap (no `maximum number of
  items` 400s) — without manual per-profile edits. *(B)*
- A model that calls an existing-but-unloaded tool succeeds via auto-load+retry
  rather than failing — verified against Groq's strict validation. *(C)*
- A behavioural test exercises the full RSS task on a strict, capped provider
  end-to-end.

## Related

- [ISSUE-008](ISSUE-008-gemini-free-tier-tpm-saturation.md) — the Gemini quota
  cap that pushed us to Groq in the first place.
- [ISSUE-007](ISSUE-007-prose-contract-drift-across-policy-layers.md) — same
  underlying theme: behaviours that depend on the model honouring a prose
  contract (here, "call tool_search first") are fragile.
- `tool_search.py`, `mcp/mcp_manager.py` (`_is_disabled`), `config-standard-groq-scout.json`.
- [model-tool-calling-and-free-apis](../research/model-tool-calling-and-free-apis.md) — provider/model tool-calling reliability.
