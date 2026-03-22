# Plan: Model Routing Simplification

## Status

**Review** — Decisions to be made. See [Decision Points](#decision-points) below.

## Problem

The semantic model routing system (ADR-020, completed 2026-03-21) attempts to classify every user prompt into one of 9 task types and dynamically route each turn to a different provider/model. In practice this is unreliable:

1. **Misrouted tool-use prompts.** "Get the last 5 emails" routes to `conversational` → `qwen2.5:7b` (Ollama). The 7B model returns 0 tokens (empty content), which then crashes the next turn when the empty assistant message is sent back to Ollama as `content: null`. The classifier has no concept of "this prompt needs to execute tools."

2. **Keyword-vector Stage 2 is not semantic.** Despite the name, Stage 2 uses cosine similarity against hardcoded keyword dictionaries — not dense embeddings. "Get the last 5 emails" scores 0.000 similarity because none of the tokens (`get`, `the`, `last`, `emails`) appear in any keyword vector. The word `emails` doesn't match `email` (no stemming).

3. **9-type taxonomy has no tool-action category.** Imperative prompts like "search for jobs", "send a message", "list my files", "check my calendar" don't fit any of the 9 task types. They're not conversational, creative, analytical, or code-related — they're tool-use commands, which is the primary use case of this agent.

4. **No production agent framework does this.** Research into Claude Code, Cursor, Aider, Roo Code, OpenHands, and OpenRouter shows that none of them attempt per-prompt semantic classification into task types for model routing. The approaches that work:
   - **User-selected modes** (Aider architect/editor, Roo Code modes, Cursor custom modes)
   - **Fixed splits** (expensive model reasons, cheap model edits)
   - **Auxiliary-only routing** (commit messages and summarization → cheap model, everything else → main model)
   - **Sub-agent types with hardcoded models** (Claude Code: Explore → Haiku, main → Sonnet)

5. **Cross-family fallback was broken.** When Ollama fails, the provider pool fell back to Anthropic with the wrong message format, tool schema format, and model name — causing a second crash. Fixed by ADR-021 (same-family fallback), but the root cause is that the routing sends prompts to models that can't handle them.

6. **Embedding-based Stage 2 added complexity without solving the core issue.** We added real Ollama dense embeddings to replace keyword vectors, but even with perfect semantic matching, the 9-type taxonomy still has no category for tool-use actions — the most common prompt type in this agent.

### Bugs Fixed During Investigation

- **ADR-021: Same-family provider fallback** — Pool now only falls back within the same provider family (anthropic/openai/gemini). Cross-family fallback is blocked.
- **Empty content crash** — `_to_openai_messages` now emits `content: ""` instead of `content: null` when an assistant message has an empty content list with no tool calls.
- **Embedding-based Stage 2** — `classify_stage2` now uses dense Ollama embeddings when available, falling back to keyword vectors when not.

## Research: What Works in Production

| Framework | Routing Approach | Model Selection |
|-----------|-----------------|-----------------|
| **Aider** | Architect/Editor/Weak fixed split | User picks modes; weak model for commit msgs + summarization only |
| **Claude Code** | Sub-agent types | Hardcoded: Explore → Haiku, main → Sonnet/Opus |
| **Cursor** | Auto mode (server-side) | User-selected or "auto" based on query complexity |
| **Roo Code** | 5 named modes (Architect/Code/Debug/Ask/Custom) | Each mode → different model via config |
| **OpenHands** | No internal routing | Single model for everything |
| **OpenRouter** | Auto Router (NotDiamond) | API-level routing with massive telemetry — not agent-level |

**Key insight:** Successful frameworks route by *role* (planner vs executor vs auxiliary) or *user selection*, not by per-prompt semantic classification. The 70/30 rule (70% of traffic is simple, 30% needs reasoning) is captured by role-based splits, not 9-type taxonomies.

## Options

### Option A: Simplify to Guard-Based Routing

Keep the routing infrastructure but replace the 9-type classifier with simple guards:

1. **Tool-use guard** (new): If tools are available and the prompt is not a greeting/acknowledgement, route to the main model. This is the single biggest fix — it prevents misrouting of the most common prompt type.
2. **Trivial guard** (keep): Greetings, yes/no, thanks → cheap model. Already works well via Stage 1 rules.
3. **Tool continuation** (keep): Iteration > 0 → pin to the model that started the turn. Already works.
4. **Everything else** → main model.

**Pros:** Simple, reliable, still saves money on trivial turns (~30-40% of traffic). No ML, no embeddings, no keyword vectors.
**Cons:** Gives up potential savings on conversational/factual turns that don't need tools.

### Option B: Add Tool-Action Task Type + Embedding Fix

Keep the 9-type taxonomy, add a 10th type (`tool_action`), and rely on the embedding-based Stage 2 to classify correctly:

1. Add `tool_action` to `TaskType` enum with a rich description for embedding.
2. Route `tool_action` to the main model.
3. Keep the embedding-based Stage 2 for all other classifications.

**Pros:** Preserves the full routing system and its potential cost savings.
**Cons:** Still depends on embedding quality for correct classification. Adds another task type without evidence that the taxonomy approach works in production. The fundamental problem (per-prompt classification is unreliable) remains.

### Option C: Role-Based Routing (Aider Pattern)

Replace task-type routing with role-based routing:

1. **Main model**: All user-facing turns (prompt → response with possible tool use).
2. **Cheap model**: Compaction, summarization, commit messages, sub-agent explore tasks.
3. **Optional small model**: Trivial greetings only (if confidence > 0.95 from Stage 1 rules).

This matches the Aider weak-model pattern and is the most industry-aligned approach.

**Pros:** Battle-tested pattern. Simple. No classifier needed for the main path.
**Cons:** No cost savings on mid-complexity turns that a cheaper model could handle.

### Option D: Keep Current System + Tool-Use Hard Guard

Minimal change: add a single rule at the top of the routing pipeline:

```
if has_tools and not is_trivial_greeting(msg):
    → main model (skip classifier)
```

Everything else stays as-is. The classifier still runs for tool-less turns.

**Pros:** Smallest possible change. Fixes the immediate problem.
**Cons:** The classifier still has all its complexity for diminishing returns. Keyword vectors and embedding infrastructure remain for limited benefit.

## Decision Points

### D1: Which option?

Options A through D trade off simplicity vs potential cost savings. The data point: **no production agent framework has made per-prompt semantic routing work reliably.** The cost savings from routing trivial turns to cheap models are real but modest compared to prompt caching and tool search (which are already implemented).

### D2: What happens to the embedding infrastructure?

The `TaskEmbeddingIndex` and embedding-based Stage 2 were just added. Options:
- **Keep for tool search only** — `ToolEmbeddingIndex` is valuable and working. Remove `TaskEmbeddingIndex`.
- **Keep both** — task embeddings may be useful for future analytics/observability even if not used for routing.
- **Remove task embeddings** — if we go with Option A or C, they're dead code.

### D3: What happens to the routing feedback loop?

`RoutingFeedbackStore` records routing outcomes to SQLite. If routing is simplified:
- **Keep for observability** — still useful to see what the classifier *would have* chosen, even if we don't act on it.
- **Remove** — if routing is simplified enough that feedback is meaningless.

### D4: Keep or remove the provider pool?

The `ProviderPool` with same-family fallback (ADR-021) is useful infrastructure even without semantic routing — it enables:
- Health tracking with exponential backoff
- Same-family fallback for resilience
- Cache-aware provider switching

All options keep the pool. The question is whether it dispatches based on classifier output or simple guards.

## Impact

### What stays regardless of option chosen

- Provider pool with same-family fallback (ADR-021)
- Prompt caching (Layer 1)
- Tool search / schema reduction (Layer 2)
- Conversation compaction with cheap model (Layer 3)
- Session budgets (Layer 4)
- Concise output formatting (Layer 5)
- Per-policy overrides: `tool_search_only`, `compact` system prompt, `pin_continuation`

### What may change

- Semantic classifier (simplify or remove Stage 2 keyword/embedding path)
- Task taxonomy (simplify or remove)
- Routing policies in config (simplify to fewer cases)
- `TaskEmbeddingIndex` (remove or keep for analytics)

## Related

- [ADR-012: Layered Cost Reduction](../architecture/decisions/ADR-012-layered-cost-reduction.md) — parent architecture
- [ADR-020: Semantic Model Routing](../architecture/decisions/ADR-020-semantic-model-routing.md) — current system being reviewed
- [ADR-021: Same-Family Provider Fallback](../architecture/decisions/ADR-021-same-family-provider-fallback.md) — bug fix during investigation
- [PLAN-semantic-model-routing.md](PLAN-semantic-model-routing.md) — original implementation plan (completed)
- [PLAN-cost-reduction.md](PLAN-cost-reduction.md) — broader cost reduction context
