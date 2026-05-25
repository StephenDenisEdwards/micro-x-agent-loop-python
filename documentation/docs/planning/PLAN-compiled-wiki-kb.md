# Plan: Compiled-Wiki Knowledge Base

## Status

**Research** — placeholder reminder. No implementation work scheduled. See [compiled-wiki-knowledge-base.md](../research/compiled-wiki-knowledge-base.md) for the full pattern and analysis.

## Reminder

This plan exists so that a known-good idea does not get lost. The user explored the Karpathy-style "compiled wiki" / context-engineering pattern in conversation, found that **the minimum viable version requires zero code changes** (just a directory and a habit), and asked for a forward-pointing record so the topic can be revisited deliberately at some later point.

If you (a future agent or a future me) are reading this and considering work on long-term memory, context engineering, knowledge-base features, or anything in the neighbourhood, **read the research doc first**.

## Problem

The agent has session-scoped memory (`.micro_x/memory.db`) and project-scoped user memory (`.micro_x/memory/MEMORY.md`), but no curated, durable, cross-session **semantic knowledge layer**. Raw event logs and ephemeral compaction summaries are not the same as a maintained body of canonical knowledge.

Symptoms this would address:

- Repeated re-explanation of project decisions, entities, and conventions.
- Loss of distilled understanding from prior sessions once compaction discards old turns.
- No place to record an evolving, agent-readable view of any *subject* (work projects, research themes, personal domains) that the user collaborates with the agent on.
- Retrieval today is either keyword tool-search or full conversation history — no "what does the agent *know* about X?" layer.

## Why this is not being built yet

Three honest reasons:

1. **The zero-code version may capture most of the value.** See Option 0 in the research doc. A `wiki/` directory plus a manual end-of-session habit plus a line in `CLAUDE.md` requires no Python changes at all. The research doc recommends running this manual version for at least a few weeks before committing to infrastructure, because the page structure that *actually* works is impossible to design upfront.
2. **Wiki rot is the real failure mode.** Compiling pages that are never read in agent context turns into expensive logs. Any code-changes work has to commit to retrieval (Layer 4) alongside storage (Layer 3) — and we should validate retrieval quality with the zero-code version first.
3. **Other priorities are higher.** Cost reduction, routing, MCP publishing, behavioural evals all have clearer near-term ROI.

## When to revisit

Pull this plan off the shelf if any of these become true:

- The user has been running the manual / zero-code version (Option 0) for ≥ 2 weeks and finds it valuable but tedious — at that point the broker-cron version (Option 1) becomes obviously worth it.
- Retrieval quality of "LLM grepping markdown" proves insufficient at scale (many subjects, many pages) — at that point the embedded `wiki_search` pseudo-tool (Option 2) becomes worth it.
- A specific use case demands strict cross-session continuity of distilled knowledge (e.g. a long-running client engagement, a multi-month research project, a regulated/auditable knowledge trail).
- A feature is proposed that would duplicate parts of this design (e.g. "save key facts", "remember decisions across sessions"). Check this plan first — it may be the right umbrella.

## Phased shape (when work eventually starts)

The research doc identifies four ambition levels. Implementation should climb the ladder, not skip rungs.

### Phase 0 — Manual habit (zero code)

- Create `wiki/` directory with `entities/`, `topics/`, `decisions/`, `INDEX.md`.
- Add a `CLAUDE.md` directive pointing the agent at `wiki/INDEX.md`.
- Adopt the end-of-session habit: ask the agent to update the wiki.
- Run for ≥ 2 weeks. Discover what page shapes work.

**Exit criteria:** the user has a clear answer to "is this valuable enough to automate?" and concrete evidence about which page structures and conventions are load-bearing.

### Phase 1 — Scheduled consolidation (config only)

- Author `prompts/consolidate.md` as a reusable consolidation prompt.
- Add a broker cron job (e.g. `0 */6 * * *`) that runs `--run "$(cat prompts/consolidate.md)"`.
- Pin the consolidator job to a cheap model via `RoutingPolicies`.
- Wire contradiction flags through the broker HITL question flow.

**Exit criteria:** consolidation happens reliably without user prompting; wiki stays coherent across a one-week window of normal use.

### Phase 2 — Minimal code (optional)

Only if Phase 1 reveals that filesystem-grep retrieval is not enough:

- `src/micro_x_agent_loop/memory/wiki_store.py` — read/write markdown with frontmatter, maintain backlinks, embed on write (reusing `embedding.py` and a new `.micro_x/wiki.db`).
- A `wiki_search(query)` pseudo-tool returning top-k pages by embedding similarity.
- A new sub-agent type `consolidator` in `sub_agent.py` (system prompt, write-targets, HWM handling).

### Phase 3 — Pre-turn auto-injection (the "true Karpathy" move)

Only if Phase 2 retrieval is good but the LLM under-uses it:

- `agent.py` performs pre-turn embedding of the user prompt, fetches top-k pages, prepends them to context.
- Solve the prompt-caching interaction (pages must live in a cache-stable slot or the cache prefix invariants must be preserved).

### Multi-subject management

Independently of phasing, support both subject patterns documented in the research doc:

- **Pattern A:** subdirectories under one `wiki/` with a router `INDEX.md` — recommended default.
- **Pattern B:** separate working directories per subject — when hard isolation is required.

Plus a session convention: `--session work-current`, `--session research-llm-kb`, etc., one persistent session per subject.

## Non-goals

- **No "automatic entity resolution"** beyond what the LLM does in-prompt. We are not building a knowledge-graph database.
- **No replacement of the existing memory system.** This sits alongside `.micro_x/memory.db` (raw) and `.micro_x/memory/MEMORY.md` (user preferences), not on top of either.
- **No bespoke wiki-rendering UI.** Pages stay as markdown on disk. The user's editor / any markdown viewer is the UI.
- **No real-time consolidation.** Even Phase 1 is batched on a cron, not triggered per-event. Continuous consolidation is too expensive and offers no obvious benefit over hourly batches.

## Risks / open questions

(Carried forward from the research doc — these should be resolved before serious implementation work.)

- **Cache interaction with Phase 3:** Pre-turn injection changes the system-prompt prefix per turn. May break prompt caching.
- **What does the consolidator read?** Raw `memory.db` events, a pre-filtered digest, or per-page HWMs? Affects token cost and consolidation quality.
- **Schema enforcement:** strict frontmatter is fragile. Soft conventions plus a periodic "wiki-lint" job is probably the right answer.
- **Cross-wiki linking under Pattern A:** can entities in `work/` legitimately link to `research/`? Where is the boundary policed?
- **Migration path:** if a Pattern A subject grows into Pattern B, how is the existing subject directory cleanly promoted to its own project root?
- **Contradiction false positives:** how to keep HITL load manageable.

## References

- [compiled-wiki-knowledge-base.md](../research/compiled-wiki-knowledge-base.md) — full research doc.
- [PLAN-claude-style-memory.md](PLAN-claude-style-memory.md) — file-based user memory; shares the markdown-as-canonical-store philosophy.
- [PLAN-cross-session-user-memory.md](PLAN-cross-session-user-memory.md) — precedent for `CLAUDE.md`-injected memory content.
- [PLAN-sub-agents.md](PLAN-sub-agents.md) — `summarize` sub-agent type; baseline for a future `consolidator`.
- [PLAN-trigger-broker.md](PLAN-trigger-broker.md) — the cron host for Phase 1+.
- [deep-research-compaction.md](../research/deep-research-compaction.md) — adjacent work on context window management.
- [rag-and-alternatives-research-report.md](../research/rag-and-alternatives-research-report.md) — broader context on retrieval alternatives.
