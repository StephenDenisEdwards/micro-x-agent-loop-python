# Compiled-Wiki Knowledge Base Pattern

Research notes on the Karpathy-style "compiled wiki" / context-engineering pattern and how it maps onto the micro-x-agent-loop architecture.

## Background

In 2026, Andrej Karpathy publicly argued for **context engineering over prompt engineering**: the real challenge with LLM-driven systems is not crafting clever prompts but supplying the right information, in the right structure, at the right time. A specific architectural pattern emerged from his commentary — the *compiled wiki* or *compiled knowledge base*.

The core claim:

> Instead of storing chunks in a vector DB and retrieving them ad hoc, use LLMs to continuously compile knowledge into an evolving, human-readable wiki/markdown knowledge system.

### Traditional RAG vs. compiled wiki

| Stage | Traditional RAG | Compiled wiki |
|-------|-----------------|---------------|
| Source | Documents | Documents |
| Transform | Chunk → embed | LLM synthesis (entities, summaries, topics) |
| Store | Vector index | Structured markdown pages, interlinked |
| Retrieve | Top-k chunk similarity | Curated semantic pages (or pre-injected) |
| Maintenance | Re-index on change | Continuous LLM-driven refactor / consolidation |

The LLM stops being a search-engine consumer and becomes the **librarian, editor, and compiler** of the knowledge base.

### Compiler analogy

| Traditional software | Compiled-wiki KB |
|----------------------|------------------|
| Source code | Raw documents (chats, emails, code, PDFs, logs) |
| Compiler | LLM synthesis process |
| Binary | Structured context package (markdown pages) |
| Runtime | Agent execution |
| Optimisation passes | Continuous summarisation / refactoring |

The "knowledge compiler" cleans and reorganises noisy, duplicated, contradictory, badly-structured raw inputs into canonical pages.

### Why this matters

Naive RAG often retrieves irrelevant chunks, loses semantic hierarchy, duplicates information, destroys narrative structure, and lacks abstraction layers. A compiled wiki maintains topic hierarchy, summaries, canonical truths, linked concepts, evolving interpretations, and distilled reasoning. The system resembles human long-term memory consolidation — hippocampus → cortex abstraction — rewriting raw experience into compressed semantic structures.

### Five-layer reference architecture

1. **Raw store** — PDFs, chats, code, emails, logs.
2. **Extraction** — entity extraction, summaries, relationship extraction, topic detection.
3. **Knowledge wiki** — markdown pages, backlinks, semantic sections, canonical entities.
4. **Agent context engine** — retrieves synthesised pages, injects relevant context, maintains working memory.
5. **Reflection / maintenance** — merge duplicates, detect contradictions, update stale knowledge, compress history.

### The deeper shift

> **Old assumption:** LLMs are stateless tools with retrieval attached.
> **New assumption:** LLMs are evolving cognitive systems with working memory, episodic memory, semantic memory, reflection loops, and self-maintained abstractions.

## Fit with micro-x-agent-loop

This project is unusually well-positioned to host a compiled-wiki KB. The five layers map cleanly onto existing infrastructure.

| Layer | Existing mechanism | Gap |
|-------|-------------------|-----|
| 1. Raw store | `.micro_x/memory.db` (messages, tool_calls, events, checkpoint_files) | None |
| 2. Extraction | `compaction.py` summaries (ephemeral); `SubAgentRunner` `summarize` type (on-demand) | No persistent extraction; no entity/relationship store |
| 3. Knowledge wiki | — | **No on-disk markdown KB, no canonical entities, no backlinks** |
| 4. Agent context engine | `tool_search.py` + `embedding.py` (Ollama embeddings); `system_prompt.py` assembly | No pre-turn wiki injection |
| 5. Reflection / maintenance | Compaction; broker daemon can run cron jobs | No consolidation loop, no contradiction detection |

Three project capabilities make this serendipitously easy:

- **Broker daemon** (`broker/service.py`) is already a long-running cron host — a reflection loop is just another scheduled job.
- **Sub-agents** (`sub_agent.py`) already include a `summarize` type that is ~90% the shape of a "compiler" agent.
- **Embeddings + vector index** (`embedding.py`) exist for tool search; the same machinery can index wiki pages.

## Implementation options, from minimal to elaborate

The pattern can be realised at four different ambition levels. The interesting finding from this research is that the **lowest-ambition version requires zero code changes** and may capture most of the value.

### Option 0 — Manual habit (zero code, zero infrastructure)

The minimum viable shape is just **a directory and a habit**:

```
wiki/                     # anywhere — project root, ~/wiki, etc.
  entities/{name}.md
  topics/{slug}.md
  decisions/{adr-id}.md
  INDEX.md                # auto-maintained table of contents and backlinks
```

The user, at the end of a session, says to the agent:

> "Update `wiki/` based on what we discussed today. Touch any pages that need it, create new ones if needed, keep `INDEX.md` current."

The filesystem MCP server handles reads/writes. The LLM does the synthesis. The user decides when to compile. **Nothing else is needed.**

A line in `CLAUDE.md` makes the wiki accessible to future sessions:

> "Before answering questions about project history, decisions, or entities, check `wiki/INDEX.md` and read relevant pages."

**Trade-offs:**
- Forgetting to consolidate = stale wiki.
- Headless `--run` sessions are not captured unless the prompt explicitly asks for consolidation.
- Total user control of timing, model used, and content.
- Zero infrastructure cost.

### Option 1 — Scheduled consolidation (config only, no code)

Add a broker cron job that fires the same consolidation prompt automatically:

```bash
python -m micro_x_agent_loop --job add wiki-consolidate \
  "0 */6 * * *" \
  "$(cat prompts/consolidate.md)"
```

The prompt template (`prompts/consolidate.md`) instructs the LLM to:

1. Read `wiki/INDEX.md` to find pages potentially affected by recent activity.
2. For each affected page: read existing content, merge new information, rewrite.
3. Update `INDEX.md` backlinks.
4. Flag contradictions via `task_create` for human review.

Everything is config + prompt. No Python touched.

**Trade-offs:**
- Forces consolidation even when the user forgets.
- Token-heavy — pin to a cheap model via `RoutingPolicies`.
- Risk of false-positive contradictions; mitigate with broker HITL question flow.

### Option 2 — Minimal code (wiki store + retrieval pseudo-tool)

If retrieval quality from raw filesystem reads proves insufficient, add two pieces of Python:

1. **`memory/wiki_store.py`** — read/write markdown pages with frontmatter (`entities:`, `links:`, `updated_at`, `source_events:`); maintain backlink index; embed on write into a dedicated `.micro_x/wiki.db` (reusing `embedding.py`).
2. **A `wiki_search(query)` pseudo-tool** — returns top-k pages by embedding similarity. LLM decides when to pull.

This is the smallest code-change version. Still no changes to `turn_engine.py`.

### Option 3 — Pre-turn auto-injection (the "true Karpathy" move)

`agent.py` performs an automatic pre-turn wiki retrieval: embed the user prompt, fetch top-3 pages, prepend them to the system prompt before the LLM call. Context is *engineered*, not *requested*.

This is where the pattern delivers its full theoretical value but also where it interacts non-trivially with prompt caching (the prepended block changes per turn — care needed to keep the cache prefix stable).

## Multi-subject management

Once the pattern works for one subject, users will want multiple subject-specific wikis (work, research, personal, per-client engagement, etc.). Two main patterns emerged:

### Pattern A — One wiki, subject subdirectories

```
wiki/
  INDEX.md              # router: "work → work/, research → research/..."
  work/
    INDEX.md
    entities/
    topics/
  research/
    INDEX.md
    ...
  personal/
    ...
```

The top-level `INDEX.md` acts as a router the agent reads first. `CLAUDE.md` directs the agent to consult it before drilling in.

- **Good for:** related-ish subjects, cross-cutting queries, single launch point, low ceremony.
- **Bad for:** strict isolation. Discipline lives in the `CLAUDE.md` directive, not the filesystem.

### Pattern B — Separate working directories

```
~/kb-work/      wiki/ + CLAUDE.md + .micro_x/
~/kb-research/  wiki/ + CLAUDE.md + .micro_x/
~/kb-personal/  wiki/ + CLAUDE.md + .micro_x/
```

Each subject is its own project root with its own `CLAUDE.md`, memory DB, and broker state.

- **Good for:** hard boundaries (confidential or regulated content), per-subject configs (e.g. cheaper model for personal, premium for work).
- **Bad for:** cross-cutting queries; must launch the agent in each directory separately.

### Session convention

Pair each subject with a persistent session so the agent retains conversational continuity within that subject:

```bash
python -m micro_x_agent_loop --session work-current
python -m micro_x_agent_loop --session research-llm-kb
python -m micro_x_agent_loop --session personal-finances
```

The session is *what the agent has talked about*; the wiki is *what's been compiled*.

### Cross-cutting queries under Pattern B

- **Symlink trick:** read-only meta-root with `~/kb-meta/wiki/{work,research,personal}` symlinked in.
- **Cross-wiki MCP server:** a thin TS MCP that exposes `search_all_kbs(query)` (requires code).
- **Manual federation:** launch the agent in each directory and aggregate yourself.

### Recommendation

Start with **Pattern A** (subdirectories). Strictly less ceremony, and boundary discipline lives in `CLAUDE.md` rather than the filesystem. Graduate individual subjects to Pattern B only if a compliance or privacy reason demands hard isolation. This mirrors how Obsidian vault users behave in practice.

The router `INDEX.md` is the choke point once subjects grow past ~10. Keep it boring and stable — a flat table with subject / path / scope columns.

## Key insights

1. **The agent loop is already a context-engineering substrate.** The TS-MCP-only tool policy and existing filesystem MCP mean the agent can be its own knowledge compiler with no Python changes.
2. **The cron job is an optimisation on a habit.** Manual consolidation should come first — it doubles as a learning loop to discover what page structure actually works for the user's retrieval patterns.
3. **Markdown beats embeddings for the user.** Markdown is inspectable, versionable, git-friendly, and human-editable. Embeddings remain useful as a retrieval layer over the markdown, not as a replacement.
4. **Wiki rot is the real failure mode.** If pages are compiled but not consumed in agent context, they become expensive logs. Tie Layer 3 (wiki) work to at least the `wiki_search` pseudo-tool (Layer 4) before investing further.
5. **Contradiction handling is socially hard.** The compiler will produce false-positive contradictions; plan for HITL review via the broker's existing question/answer flow.
6. **Pattern A subdirectories scale further than expected** — the filesystem provides the isolation people think they need, and `CLAUDE.md` discipline is usually sufficient.

## Open questions

- **Cache interaction:** Pre-turn auto-injection (Option 3) changes the system-prompt prefix per turn. Does it break the prompt-caching prefix? Would the pages need to live in a cached-suffix slot instead?
- **What does the consolidator read?** `memory.db` events directly? A pre-filtered "recent activity" digest? A high-water mark per page?
- **Schema enforcement:** strict frontmatter is fragile (LLM occasionally mangles). Soft conventions + a periodic "wiki-lint" job?
- **Cross-wiki linking:** under Pattern A, can entities in `work/` legitimately link to entities in `research/`? How is the boundary policed?
- **Migration path:** if a user starts with Pattern A and one subject grows into Pattern B, how is the existing subject directory promoted to its own project root cleanly?

## References (external)

- Karpathy "personal knowledge base" / "context engineering" public posts (2026).
- VentureBeat breakdown of the compiled-wiki architecture (2026).
- DAIR.AI summary of context engineering.
- Emerging academic discussion around "companion knowledge systems".

## Related project documents

- [PLAN-compiled-wiki-kb.md](../planning/PLAN-compiled-wiki-kb.md) — placeholder plan tracking eventual implementation.
- [PLAN-claude-style-memory.md](../planning/PLAN-claude-style-memory.md) — file-based user memory (`.micro_x/memory/MEMORY.md`); shares the markdown-as-canonical-store philosophy.
- [PLAN-cross-session-user-memory.md](../planning/PLAN-cross-session-user-memory.md) — auto-loaded user memory; precedent for the `CLAUDE.md` injection pattern.
- [PLAN-sub-agents.md](../planning/PLAN-sub-agents.md) — `summarize` sub-agent type; baseline for a future `consolidator` type.
- [PLAN-trigger-broker.md](../planning/PLAN-trigger-broker.md) — the cron host that would run scheduled consolidation.
- [deep-research-compaction.md](deep-research-compaction.md) — adjacent work on context window management.
- [rag-and-alternatives-research-report.md](rag-and-alternatives-research-report.md) — broader context on retrieval alternatives.
