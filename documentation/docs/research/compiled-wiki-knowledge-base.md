# Compiled-Wiki Knowledge Base Pattern

## Links
https://x.com/karpathy/status/2039805659525644595?s=46&t=so-d50SiR5Zy2uoiwnsjnw

https://youtu.be/ib74sLgjIBM?si=O6IPy4u_1UTBx2Du 

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

## External reference implementation — Claude CoWork Knowledge Base Kit

A drop-in starter kit published by Systems Made Better (`bettercreating.com`) implements the same Karpathy pattern as a Claude CoWork extension. It is opinionated where this research is deliberately open. Several of its choices fill gaps in the architecture above and are worth adopting wholesale rather than reinventing.

The kit ships:

- `KNOWLEDGE/CLAUDE.md` — top-level librarian operating manual.
- `KNOWLEDGE/_KB_CLAUDE_TEMPLATE.md` — per-KB CLAUDE.md template.
- `KNOWLEDGE/_SCHEDULED_TASK_TEMPLATE.md` — monthly health-check setup one-pager.
- `knowledge-base-health-check-skill.skill` — the consolidation/audit skill itself.

### Three-folder split on disk

CoWork puts RAW on the filesystem alongside Wiki, not in the agent's memory DB:

```
KNOWLEDGE/[topic]_kb/
├── CLAUDE.md          — per-KB librarian rules
├── CHANGELOG.md       — running log; top entry = current state
├── RAW/
│   └── _INGESTED.md   — registry of every source
├── Wiki/
│   ├── INDEX.md
│   ├── QUESTIONS.md   — open threads, gaps, held tensions
│   └── *.md           — articles
└── Outputs/           — dated question reports with citations
```

This makes provenance verifiable by humans, not only the agent. RAW is verbatim and never edited after ingest — the rule that makes everything else trustworthy.

### A new layer: Outputs

CoWork adds a layer the five-layer architecture lacks. Every question becomes a dated report (`YYYY-MM-DD_query-slug.md`) under `Outputs/`, with citations back to the Wiki articles and RAW sources it drew on. Strong reports get promoted back into the Wiki. This closes the loop that *Key insight 4* (wiki rot) gestures at — synthesis is replayed and re-fed, not just compiled and abandoned.

### Concrete conventions worth importing

| Concern | CoWork's answer |
|---------|-----------------|
| KB folder name | `[topic]_kb` (snake_case, suffix-anchored) |
| Article filename | kebab-case, lowercase (`deep-work.md`) |
| Backlinks | `[[topic-name]]` matching the filename |
| RAW frontmatter | `title, author, source_url, date_added, date_published, type, tags` |
| Wiki frontmatter | `Status, Last updated, Sources, Summary, Body, Related, Open Questions` |
| Article trust level | `established` / `emerging` / `speculative` |
| Promotion rule | `emerging → established` requires ≥2 independent supporting sources |
| Claim provenance | Every Wiki claim traces to ≥1 RAW source, or the article is marked `speculative` |
| Cut-off for next compile | `_INGESTED.md` — registry timestamp per RAW file |
| Writing rules | Loaded from workspace-level `ABOUT ME/writing-rules.md`; navigation files exempt |

### Contradictions are embraced, not reconciled

This research lists contradiction handling as an open question requiring HITL. CoWork resolves it: when two articles disagree, add `**Counterpoint:** [[other-article]] argues...` to each, and log the tension under a "Held tensions" heading in `QUESTIONS.md`. Two well-sourced articles disagreeing is a feature, not a defect. No reconciliation attempt — the corpus is allowed to hold opposing positions.

### Inverted defaults for question vs. drafting

- **Question answering**: Wiki first, RAW second, web search *offered* but never run automatically. Conserves the corpus.
- **Article drafting**: web search freely; primary sources land in `RAW/` first (with full frontmatter, registered in `_INGESTED.md`) before the Wiki article cites them. Expands the corpus.

Same agent, opposite default, depending on whether the operation is read or write.

### State tracking — what's been read and what's been updated

CoWork's tracking is entirely markdown-native, no database. Three files do the work, each at a different granularity:

- **`RAW/_INGESTED.md` — per-source registry.** Append-only log. One entry per RAW file with filename, date added, source URL, one-line summary. If a file is in `RAW/` but not in `_INGESTED.md`, it hasn't been ingested yet. This is the cut-off the consolidator reads to find "new since last compile."
- **Wiki article frontmatter — per-article state.** Every Wiki article declares `Last updated: YYYY-MM-DD` and `Sources: [[raw-file-1]], [[raw-file-2]]`. Combined with the registry, both directions are derivable: "what does this article cite?" and "which articles cite this RAW file?"
- **`CHANGELOG.md` — per-KB state.** Running log at the KB root, most recent entry at top, explicitly defined as both history *and* current-state memory. Each compile pass writes an entry: N files processed, articles created, articles updated, pending items moved to `QUESTIONS.md`. The health-check skill reads the top entry to decide whether to skip (no compile or new output since last check → write a skip line and stop).

**Self-healing via the health check.** Because LLMs sometimes mangle these files, the monthly audit has an "orphan RAW registration" auto-fix category — if a RAW file has valid frontmatter and fits the KB's focus areas but isn't in `_INGESTED.md`, the health check registers it. Same for broken backlinks. The system tolerates drift between compile passes; the lint pass converges it.

The deliberate design choice: **markdown is the canonical store, no SQLite for tracking state.** Every state file is inspectable, git-versionable, and human-editable. The tradeoff is no transactional guarantees — a crashed compile can leave a half-updated Wiki and a stale `_INGESTED.md` — but the health check is the recovery mechanism, not a database transaction.

**How this maps to micro-x-agent-loop.** Two existing capabilities cover the same ground without a new database:

| CoWork mechanism | Project equivalent |
|------------------|--------------------|
| `_INGESTED.md` cut-off | `memory.db` events can derive last-compile timestamp; or the markdown file can live alongside the Wiki, owned by the consolidator sub-agent |
| `CHANGELOG.md` top-entry | Same markdown file works; or a row in `memory.db` per consolidation run |
| Health-check orphan-fix | Broker cron job invoking a `consolidator` sub-agent — exactly the Option 1 / Option 2 shape from above |

The pragmatic call: **keep the markdown files as the canonical store** (inspectable, git-friendly, matches CoWork's working pattern) and let `memory.db` remain the raw event log it already is. The consolidator reads `memory.db` for "what happened since last run" and writes `_INGESTED.md` / `CHANGELOG.md` as the durable, human-readable state.

### The consolidation skill

The health-check skill is a concrete instance of Option 1 / Option 2 in this research's "Implementation options" section. Its operational details transfer directly:

- **Skip-if-no-changes precondition** — if the top `CHANGELOG.md` entry is itself a health check with no compile or new output since, the run writes a skip line and stops. Free in the common case.
- **Delta vs. full audit cadence** — delta most months; full audit on the 1st of Jan/Apr/Jul/Oct.
- **Auto-fix categories**: writing-rules violations, broken backlinks, em-dash bullet patterns, orphan RAW registration, `emerging → established` promotions, contradiction cross-references, gap mirroring into `QUESTIONS.md`.
- **Flag-only categories** (no auto-action): out-of-scope RAW, output promotion candidates, stale articles needing voice rewrites, ambiguous banned-word swaps.
- **Hard cap of 3 auto-drafted articles per run** with explicit "Article candidate held — insufficient evidence" logging in lieu of fabrication.
- **One sub-agent per KB at run time** — keeps token use linear in KB count rather than quadratic in corpus size.

The last point maps directly onto `SubAgentRunner`: a `consolidator` sub-agent type per KB, spawned in parallel, each scoped to one subject.

### Multi-KB convention

CoWork resolves the Pattern A / Pattern B tension by hybridising them. One `KNOWLEDGE/` root contains many `[topic]_kb/` subdirectories (Pattern A), but each has its own `CLAUDE.md` (a Pattern B trait). Cross-KB queries aren't a built-in feature — they're a user move, asking the librarian to consult multiple KBs explicitly. This pushes the boundary discipline into per-KB `CLAUDE.md` files rather than the filesystem.

### What CoWork doesn't address that we still need

- **Pre-turn auto-injection** (Option 3). CoWork is fully agent-driven — the user (or scheduled task) triggers reads and writes. There is no context engine that pulls Wiki pages before each turn.
- **Embedding-backed retrieval** over Wiki pages. CoWork relies on filename and `INDEX.md` lookup — fine at small scale, gets brittle past dozens of articles.
- **Cache-stability strategy** for prepending Wiki content to system prompts.

These remain open for our implementation.

## Open questions

- **Cache interaction:** Pre-turn auto-injection (Option 3) changes the system-prompt prefix per turn. Does it break the prompt-caching prefix? Would the pages need to live in a cached-suffix slot instead?
- **Cross-wiki linking:** under Pattern A, can entities in `work/` legitimately link to entities in `research/`? How is the boundary policed? CoWork sidesteps this by treating each KB as standalone — does that scale to our use cases?
- **Migration path:** if a user starts with Pattern A and one subject grows into Pattern B, how is the existing subject directory promoted to its own project root cleanly?
- **Embedding layer over Wiki:** at what corpus size does `INDEX.md` + filename lookup stop being enough? When do we need `embedding.py` over Wiki pages?

### Resolved by external reference implementations

- ~~**What does the consolidator read?**~~ → `_INGESTED.md` provides a per-RAW-file cut-off; `CHANGELOG.md` top entry provides a per-KB cut-off.
- ~~**Schema enforcement** for fragile frontmatter?~~ → A periodic "wiki-lint" pass (the CoWork health check) auto-fixes routine drift and flags the rest. Confirmed viable.
- ~~**Contradiction handling**~~ → Don't reconcile; cross-reference and log under "Held tensions". Avoids the HITL bottleneck entirely.

## References (external)

- Karpathy "personal knowledge base" / "context engineering" public posts (2026).
- VentureBeat breakdown of the compiled-wiki architecture (2026).
- DAIR.AI summary of context engineering.
- Emerging academic discussion around "companion knowledge systems".
- **Claude CoWork Knowledge Base Kit v1** (Systems Made Better / bettercreating.com) — drop-in starter kit implementing the pattern as a CoWork extension. Local copy at `C:\Users\steph\source\repos\Claude-CoWork-Knowledge-Base-Kit_v1\`. Includes `Get-Started-Guide.pdf`, `KNOWLEDGE/CLAUDE.md`, `_KB_CLAUDE_TEMPLATE.md`, `_SCHEDULED_TASK_TEMPLATE.md`, and the `knowledge-base-health-check-skill.skill` bundle.

## Related project documents

- [PLAN-compiled-wiki-kb.md](../planning/PLAN-compiled-wiki-kb.md) — placeholder plan tracking eventual implementation.
- [PLAN-claude-style-memory.md](../planning/PLAN-claude-style-memory.md) — file-based user memory (`.micro_x/memory/MEMORY.md`); shares the markdown-as-canonical-store philosophy.
- [PLAN-cross-session-user-memory.md](../planning/PLAN-cross-session-user-memory.md) — auto-loaded user memory; precedent for the `CLAUDE.md` injection pattern.
- [PLAN-sub-agents.md](../planning/PLAN-sub-agents.md) — `summarize` sub-agent type; baseline for a future `consolidator` type.
- [PLAN-trigger-broker.md](../planning/PLAN-trigger-broker.md) — the cron host that would run scheduled consolidation.
- [deep-research-compaction.md](deep-research-compaction.md) — adjacent work on context window management.
- [rag-and-alternatives-research-report.md](rag-and-alternatives-research-report.md) — broader context on retrieval alternatives.
