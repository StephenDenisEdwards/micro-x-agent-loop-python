# Execution Model Design
## How Compiled Task Mode Actually Works

**Status:** Active exploration
**Document type:** Living design document — captures iterative brainstorming, tradeoffs, and open questions

---

## 1. The Design Question

The engineering white paper establishes *that* agents should switch to compiled task mode for large, structured, or compliance-sensitive workloads. This document explores *how* — what the execution mechanism actually looks like at runtime.

The core constraint: the mechanism must be **general-purpose**. This is a personal agent, not a domain-specific pipeline. The agent cannot require pre-built runtimes for every task type it might encounter.

---

## 2. Three Execution Models

### 2.1 Pre-Built Runtime

The LLM produces a structured task specification (JSON). A pre-existing, tested runtime interprets the specification and executes the pipeline.

**How it works:**
- The LLM outputs a task spec: data sources, extraction schema, scoring rubric, output template.
- A runtime engine — built and tested in advance — reads the spec and executes deterministic processing.
- The LLM is called back only for narrative generation from compact results.

**Strengths:**
- Execution logic is tested and stable.
- No risk of generated code bugs.
- Highly predictable behaviour.

**Weaknesses:**
- Not general-purpose. Every new task type requires a new runtime or runtime extension.
- The task spec becomes a DSL — and DSLs accumulate complexity or become limiting.
- Scales poorly to the variety of tasks a personal agent encounters.

**Verdict:** Suitable for known, recurring workloads (e.g., a daily job search report that runs the same way every time). Not viable as the general-purpose mechanism.

### 2.2 LLM-Generated Code (Fully Dynamic)

The LLM writes a complete program from scratch and executes it in a sandbox.

**How it works:**
- The LLM receives the task and writes a Python script (or equivalent) that does everything: fetches data, parses it, scores, validates, renders output.
- The script is executed in a sandboxed environment.
- The LLM may review or iterate on the code before execution.

**Strengths:**
- Fully general-purpose. Any task the LLM can reason about, it can write code for.
- No pre-built infrastructure required beyond the sandbox.
- Flexible — adapts to novel task shapes without engineering effort.

**Weaknesses:**
- Generated code is untested code. Bugs are likely, especially in edge cases.
- The LLM invents interfaces — network calls, file paths, API shapes — that may not match reality.
- Reliability problem is traded, not solved: from constraint drift in prompt mode to bugs in generated code.
- Harder to audit or trust for sensitive operations.

**Verdict:** Maximum flexibility, but the reliability gap is a real concern. The model is good at writing code, but "good" is not "guaranteed correct."

### 2.3 Hybrid: LLM-Generated Code Against Registered MCP Servers

The LLM writes a program, but programs against a known set of capabilities exposed by registered MCP servers — the same servers the agent already uses for tool calls in prompt mode.

**How it works:**
- The agent has registered MCP servers (Gmail, LinkedIn, file system, calendar, etc.) with typed schemas.
- In prompt mode, the agent calls these as tools through the agent loop.
- In compiled mode, the LLM writes a program that calls the **same MCP servers** programmatically — not through the agent loop's tool-call mechanism, but as API calls from generated code.
- The MCP server registry serves as both the agent's tool palette (prompt mode) and the SDK available to generated programs (compiled mode).
- The generated code orchestrates the full pipeline: fetch data via MCP, transform/score/validate in code, render output, write files via MCP.

**Strengths:**
- General-purpose. Whatever MCP servers are registered define what the agent can do in either mode. No pre-built runtimes per task type.
- No new infrastructure. The MCP servers already exist. They are exposed through a different interface (code imports vs tool calls), but the capabilities are identical.
- The LLM programs against known contracts. MCP server schemas provide typed interfaces — the model is not inventing APIs, it is calling documented ones. This dramatically narrows the surface area for bugs.
- Well-suited to LLM strengths. Writing code that calls well-documented APIs with typed schemas is exactly where models are most reliable.
- Inspectable before execution. The generated code can be reviewed — by the user, by the LLM itself, or by a validation pass — before it runs.
- Consistent capability model. The agent's capabilities are defined once (MCP server registration) and available in both execution modes. Adding a new MCP server expands both prompt mode and compiled mode simultaneously.

**Weaknesses:**
- Generated code is still untested, though the typed MCP schemas reduce risk significantly.
- MCP servers must be callable from generated code, not just from the agent loop. This may require an SDK or client library accessible from the sandbox.
- Error handling in generated code may be naive — network failures, rate limits, malformed responses.
- Sandboxing must be robust enough to run generated code that makes real external calls (Gmail, LinkedIn).

**Verdict:** The most promising direction. Combines general-purpose flexibility with meaningful guardrails from the MCP server contracts.

---

## 3. Why the Hybrid MCP Model is Compelling

The key insight is that the MCP server registry already represents a curated, typed catalogue of the agent's capabilities. In prompt mode, the agent loop mediates access to these capabilities. In compiled mode, the generated code accesses them directly.

This creates a clean architectural symmetry:

```
Prompt Mode:
  User prompt → LLM → tool call → MCP server → result → LLM → response

Compiled Mode:
  User prompt → LLM → generates program → program calls MCP servers →
  deterministic processing → compact results → LLM → narrative
```

Same capabilities. Same data sources. Same typed contracts. Different orchestration model.

The MCP schemas act as the "standard library" for generated programs. The LLM does not need to invent how to search Gmail or fetch a LinkedIn job posting — those interfaces are declared. It writes the orchestration, transformation, scoring, and rendering logic around them.

---

## 4. The Critical Constraint: Data Must Not Touch Context

During design exploration, a simpler approach was considered: the agent loop fetches data via normal MCP tool calls (prompt mode), saves it to intermediate files, and then generated code processes those files. This would avoid the complexity of MCP access from generated code entirely.

This approach is fatally flawed. When the agent loop calls MCP tools to fetch 30 emails and 20 job listings, those results — 50,000+ tokens of raw data — land in the conversation history. The data passes through the LLM's context even though the LLM doesn't need to reason over it. This defeats the entire purpose of compiled task mode, which exists precisely to keep bulk data out of context.

**The generated code must handle fetching itself.** Data must flow from source to file to processing to output without ever passing through the LLM's context window. This means the generated code needs direct access to MCP servers.

---

## 5. The MCP Client Library

The question of how generated code accesses MCP servers resolves cleanly once you recognise that MCP servers are just processes. The generated code can spawn MCP server instances directly, connect as a client, make calls, and get results. No special infrastructure required — just a library that wraps the mechanics.

### 5.1 The Library Interface

```python
from agent_mcp import connect

async with connect("gmail") as gmail:
    emails = await gmail.call("search", query="from:jobserve newer_than:1d")

async with connect("linkedin") as linkedin:
    jobs = await linkedin.call("search", query="(.NET OR Azure) contract UK")

# From here, pure Python — no MCP, no LLM
for job in jobs:
    job["score"] = compute_weighted_score(job, rubric)

qualified = [j for j in jobs if j["score"] >= 5]
ranked = sorted(qualified, key=lambda j: j["score"], reverse=True)

render_report(ranked, template="todays-jobs-report")
```

### 5.2 What the Library Handles

The `agent_mcp` library (working name) provides the bridge between generated code and the agent's registered MCP servers:

- **Registry lookup.** Resolves server names ("gmail", "linkedin") to their configuration from the agent's MCP server registry.
- **Process management.** Spawns the MCP server process, manages its lifecycle, shuts it down cleanly when the context manager exits.
- **Client connection.** Connects to the spawned server using the MCP protocol.
- **Credential passthrough.** Passes through authentication credentials (OAuth tokens, API keys) that the MCP servers already have access to in prompt mode.
- **Schema exposure.** Makes the server's tool schemas available to the generated code, enabling the LLM to write calls that match the expected parameters.

### 5.3 Why This Works

The library is small and focused — it is not a framework, it is connection plumbing. The complexity it absorbs is mechanical (process spawning, protocol connection, credential management), not semantic. The LLM does not need to understand the library internals. It needs to know:

- Server names (same names it already uses in prompt mode)
- Tool names and parameters (same schemas it already sees in prompt mode)
- The `connect` / `call` pattern

This is a trivial API surface. The LLM already knows how to call these servers — it does it every time it uses a tool in prompt mode. The library just provides the same access from inside generated code.

### 5.4 Architectural Symmetry

The MCP server registry now serves as a unified capability layer across both execution modes:

```
Prompt Mode:
  User prompt → LLM → tool call → agent loop → MCP server → result → LLM → response

Compiled Mode:
  User prompt → LLM → generates program →
    program imports agent_mcp →
    program spawns MCP servers directly →
    program does deterministic processing →
    program writes output →
  LLM reads compact results → narrative
```

Same servers. Same schemas. Same credentials. The only difference is who orchestrates the calls — the agent loop or the generated code.

Adding a new MCP server to the agent's registry automatically makes it available in both modes. The LLM sees it as a new tool in prompt mode and as a new `connect("server_name")` target in compiled mode.

---

## 6. LLM Calls Within Compiled Mode

### 6.1 Not All Operations Are Deterministic

The discussion so far implies a clean separation: the LLM reasons about the task upfront, generates code, and the code executes deterministically. But some operations that belong in compiled mode are not deterministic — they require language understanding that only an LLM can provide.

Consider: "List the last 100 emails from JobServe and create summaries of the content."

The batch fetch is mechanical — `agent_mcp` connects to Gmail and retrieves 100 emails. But "create summaries" requires reading each email's free-text content and producing a condensed version. This is not string manipulation or data transformation. It is a semantic operation that requires an LLM.

This does not mean the task should revert to prompt mode. Loading 100 full emails into a single conversation context is exactly the problem compiled mode exists to solve. The task is still structurally a batch pipeline — it just happens to include an LLM-dependent step.

### 6.2 Per-Item LLM Calls vs Single-Context Processing

The distinction is between two fundamentally different ways an LLM processes multiple items:

**Prompt mode (single context):** All 100 emails land in one conversation. The LLM sees them all simultaneously, reasons over the full set, and produces output in a single pass. Context grows linearly with item count. Cost grows quadratically (attention over the full context). At scale, this is the source of the cost and reliability problems documented in the white paper.

**Compiled mode (per-item calls):** The generated code loops over 100 emails. For each email, it makes a small, focused LLM call: "Summarize this email in 2-3 sentences." Each call has a bounded context — one email in, one summary out. The calls are independent and can run concurrently. Total cost scales linearly with item count, and each individual call is cheap because the context is small.

```python
from agent_mcp import connect
from agent_llm import complete

async with connect("gmail") as gmail:
    emails = await gmail.call("search", query="from:jobserve newer_than:1d")

summaries = []
for email in emails:
    summary = await complete(
        prompt=f"Summarize this email in 2-3 sentences:\n\n{email['body']}",
        max_tokens=200,
    )
    summaries.append({"subject": email["subject"], "summary": summary})
```

The critical property is preserved: bulk data never enters the main conversation context. The LLM is involved, but in bounded, independent calls orchestrated by the generated code — not in a single monolithic context that grows with the data.

### 6.3 The `agent_llm` Companion Library

Just as `agent_mcp` bridges generated code to MCP servers, an `agent_llm` library (working name) bridges generated code to the LLM for semantic operations. The interface is minimal:

- `complete(prompt, max_tokens)` — a single completion call for operations like summarization, classification, or extraction.
- Uses the same model and credentials as the agent, or a cheaper model where appropriate.
- Each call is independent — no conversation state, no message history accumulation.

The library is deliberately simple. It is not a conversation engine or an agent loop — it is a function call interface for generated code that needs language understanding as a processing step.

### 6.4 Which Operations Need LLM Calls?

Not every compiled-mode task requires per-item LLM calls. Most batch operations are purely deterministic:

| Operation | LLM Required? | Notes |
|---|---|---|
| Fetch data from sources | No | MCP calls, purely mechanical |
| Score against numeric criteria | No | Weighted scoring, threshold comparison |
| Filter by threshold | No | Comparison operator |
| Count, total, average | No | Arithmetic |
| Format as markdown/CSV/JSON | No | Template rendering |
| **Summarize free-text content** | **Yes** | Semantic compression |
| **Classify into categories** | **Yes** | Requires understanding content |
| **Extract structured fields from prose** | **Yes** | e.g., salary from job description body |
| **Generate per-item commentary** | **Yes** | e.g., "why this job matches your criteria" |

The presence of LLM-dependent steps does not change the mode decision. A task with 3 strong compiled-mode signals (batch processing, scoring, statistics) plus a summarization step is still a compiled-mode task. The summarization happens inside the generated code as a processing step, not as the orchestration model.

### 6.5 Cost Comparison: Measured vs Estimated

Early attempts at cost comparison using theoretical estimates were misleading. Estimates assumed small system prompts, few turns, and compact tool results. Actual measurements revealed that the real costs are dramatically higher than estimated, primarily because of factors that are difficult to predict from the prompt alone: system prompt size (including tool schemas), the number of API round-trips the agent actually takes, and the compounding effect of context accumulation across turns.

The following analysis uses actual measured data from running tasks against the agent loop, supplemented by estimates for compiled mode (which is not yet implemented).

#### Measured: "List the last 50 emails with summaries"

A simpler batch task was measured first: "List the last 50 emails from JobServe with the subject and then a summary of the content for each."

**Prompt mode — measured:**

| Metric | Value |
|---|---|
| Model | claude-sonnet-4-5-20250929 |
| API calls | 7 |
| Tool calls | 51 (1 gmail_search + 50 gmail_read) |
| Input tokens (non-cached) | 231,231 |
| Cache read tokens | 79,037 |
| Output tokens | 4,988 |
| Total cost | **$0.79** |
| Duration | 101 seconds |

The theoretical estimate for this task was ~$0.14 (assuming 3 turns and ~24,500 total input tokens). The actual cost was **5.6x higher** than estimated. The discrepancy comes from:

1. **7 API calls, not 3.** The LLM could not read all 50 emails in one batch of parallel tool calls — it required multiple rounds.
2. **310,268 total input tokens** (231K non-cached + 79K cache read), not 24,500. The system prompt with tool schemas, accumulated email contents, and conversation history compound across 7 API calls.
3. **Prompt caching helped but not enough.** Cache read tokens were charged at $0.30/M instead of $3/M, saving ~$0.22. Without caching, the cost would have been ~$1.01.

**Compiled mode — estimated:**

The generated code would connect to Gmail via `agent_mcp`, fetch all 50 emails (data never enters LLM context), extract subjects (code, free), then make 50 independent LLM calls for summaries.

| | Prompt (measured) | Compiled (Sonnet, est.) | Compiled (Haiku, est.) |
|---|---|---|---|
| Code generation | — | ~5,000 in / ~1,000 out | ~5,000 in / ~1,000 out (Sonnet) |
| Per-item LLM calls | — | 50 × ~600 in / ~100 out | 50 × ~600 in / ~100 out |
| Multi-turn re-reading | 310K total input | — | — |
| Total input tokens | 310,268 | ~35,000 | ~35,000 (mixed pricing) |
| Total output tokens | 4,988 | ~6,000 | ~6,000 (mixed pricing) |
| **Total cost** | **$0.79** | **~$0.19** | **~$0.04** |
| **Ratio vs prompt** | 1x | ~4x cheaper | ~20x cheaper |

Even this relatively simple batch task — fetch emails and summarise — shows a **4x cost advantage** for compiled mode at the same model tier, and **20x with model downgrading**. The theoretical estimate of $0.14 for prompt mode would have suggested compiled mode was *more expensive* at the same tier. The measured data shows the opposite.

#### Estimated: The Full Job Search Prompt

The full job search prompt is substantially more complex: search Gmail for JobServe emails, search LinkedIn for matching roles, read the full content of each, score every job against detailed criteria (technology match, seniority, rate, sector, location, IR35 status), exclude below 5/10, generate summaries and score explanations, compute statistics, and write a structured markdown report in stages.

Based on the measured data for the simpler task (310K input tokens for 50 email reads across 7 API calls), the full job search prompt — with two data sources, more tool calls, scoring, filtering, and multi-stage file writing — would likely require 10–12 API calls with even more context accumulation. A conservative estimate is 400,000–500,000 total input tokens.

**Prompt mode — estimated from measured baseline:**

| Metric | Estimate |
|---|---|
| API calls | 10–12 |
| Tool calls | 60+ (gmail_search, gmail_read × 30, linkedin_search, linkedin_get × 20, write_file, append_file × 3) |
| Total input tokens | ~400,000–500,000 |
| Output tokens | ~15,000 |
| Estimated cost | **$1.40–1.70** |

**Compiled mode — estimated:**

The generated code handles data fetching, scoring, filtering, statistics, and report rendering. LLM calls are needed only for per-item summaries and score explanations (~25 qualifying jobs) plus observations/recommendations (1 call).

| | Prompt (est. from baseline) | Compiled (Sonnet, est.) | Compiled (Haiku, est.) |
|---|---|---|---|
| Code generation | — | ~5,000 in / ~2,000 out | ~5,000 in / ~2,000 out (Sonnet) |
| Per-item LLM calls | — | 26 × ~800 in / ~200 out | 26 × ~800 in / ~200 out |
| Multi-turn re-reading | ~450K total input | — | — |
| Scoring, filtering, stats | LLM (output tokens) | Code ($0) | Code ($0) |
| Report formatting | LLM (output tokens) | Code ($0) | Code ($0) |
| **Total cost** | **~$1.50** | **~$0.19** | **~$0.06** |
| **Ratio vs prompt** | 1x | ~8x cheaper | ~25x cheaper |

#### Why Theoretical Estimates Understate Prompt Mode Cost

The measured cost of $0.79 for a "simple" 50-email task — compared to the theoretical estimate of $0.14 — reveals systematic underestimation in back-of-envelope calculations:

1. **System prompt and tool schemas are large.** The system prompt with registered tool schemas can be 5,000–10,000 tokens. This is re-read on every API call and is easy to overlook in estimates.

2. **More API round-trips than expected.** The agent required 7 API calls for 51 tool calls. Parallel tool calling has practical limits — the LLM batches tool calls across multiple responses, each requiring a full context re-read.

3. **Context accumulation compounds.** Each email content (~500–2,000 tokens) persists in the conversation history for all subsequent API calls. By the 7th call, the accumulated context includes the system prompt, all tool schemas, the user message, all assistant responses, and all 50 email contents.

4. **Prompt caching reduces but does not eliminate re-reading cost.** Cache read tokens are 10x cheaper ($0.30/M vs $3/M), but the volume is so large that even cached re-reading costs $0.024 for 79K tokens. And new (non-cached) input still dominates at $0.69.

These factors apply to all multi-tool prompt-mode tasks. The more tools called and the more data fetched, the larger the underestimation gap. Compiled mode avoids all of this by keeping bulk data out of the LLM context entirely.

### 6.7 Scaling: Linear vs Bounded

Beyond cost per run, the scaling characteristics are fundamentally different.

Prompt mode has a **hard ceiling**. At some batch size N, the total data exceeds the context window. For 100 emails at 500 tokens each, that is 50,000 tokens of data alone — already consuming a large fraction of the context window before any reasoning. At 200 emails, or with longer emails, prompt mode simply cannot process the batch. Compaction or truncation can extend the limit, but at the cost of losing information — which defeats the purpose of batch processing where completeness matters.

Compiled mode has **no upper bound on batch size**. The per-item cost is constant regardless of total batch size. Processing 100 emails or 1,000 emails costs the same per email — the total scales linearly. There is no context window to fill because each call is independent. The only constraint is wall-clock time, which can be reduced through concurrent execution of independent per-item calls.

This linear scaling is the decisive advantage for tasks where completeness is required. "Score **every** job" means every job, not "as many as fit in context."

---

## 7. Mode Selection: When to Compile vs When to Prompt

> **Note:** The presence of LLM-dependent operations (section 6) does not affect mode selection. Signals like "create summaries" indicate batch processing — a compiled-mode signal — regardless of whether the processing step is deterministic or LLM-assisted.

The agent receives a prompt. Before execution begins, it must decide: prompt mode or compiled mode? This decision uses only the information available at that point — the user's prompt and the agent's knowledge of its registered capabilities.

### 7.1 The Cost Estimation Challenge

There is a chicken-and-egg problem with cost-based switching. To estimate prompt-mode cost accurately, you need to know how much data will be fetched — but you don't know that until you fetch it. The job search prompt says "search Gmail for all JobServe emails in the last 24 hours" — that could be 5 emails or 50.

However, precision is not required. The switching decision needs a rough estimate that is good enough to distinguish "fits comfortably in context" from "will blow up the context window and the bill." Several estimation approaches are available, and they can be combined.

**LLM-based estimation.** The LLM reads the prompt and produces a rough cost estimate. It understands that "search Gmail for all JobServe emails in 24 hours" likely means dozens of emails, each substantial. It can estimate approximate item count, tokens per item, total context required, and reasoning overhead. This is a small, cheap classification call — perhaps 500 tokens of input and 200 tokens of output. Trivial compared to the cost of getting the mode wrong.

**Historical data.** If this is a recurring task (e.g., daily job search), the agent has seen previous runs. Yesterday's run fetched 32 emails totalling 45,000 tokens. Today's is likely similar. Historical execution data provides the most accurate estimates with zero LLM cost.

**Structural analysis.** Some prompts are obviously large without any estimation. "Search all emails from the last 24 hours" combined with "search LinkedIn" combined with "score each one" combined with "produce statistics" — the combinatorial structure alone signals batch processing regardless of the exact item count.

### 7.2 Beyond Cost: Other Decision Signals

Cost is one factor, but several other characteristics independently justify compiled mode regardless of estimated token cost.

**Deterministic execution requirements.** The prompt asks for operations that should produce exact, reproducible results:

- "Score each job 1-10" — scoring should be reproducible across runs.
- "Summary Statistics: Total Jobs Found: X (Y JobServe + Z LinkedIn)" — arithmetic must be exact.
- "Exclude roles scoring below 5/10" — filtering must not miss items or include items that should be excluded.
- "Include a link for each job" — mandatory field enforcement must be guaranteed, not probabilistic.

**Batch structure.** The task processes N items where N is non-trivial, applies the same operation to each item (score, classify, extract), and aggregates results across items (counts, averages, distributions). Batch processing is structurally suited to code, not to single-pass text generation.

**Output compliance.** The output has precise formatting requirements — specific templates, mandatory fields per item, cross-referencing requirements (anchor links between sections), or audit-trail needs. These are constraints that probabilistic generation can violate but deterministic rendering cannot.

**Reproducibility.** Tasks described as recurring ("run this same search daily") or where comparison across runs is expected require deterministic execution to produce meaningful results.

### 7.3 A Three-Stage Decision Framework

Mode selection operates as a pipeline of increasing cost and precision.

**Stage 1: Structural classification (rule-based, zero LLM cost)**

Pattern-match the prompt against known signals before involving the LLM at all:

| Signal | Detection Pattern | Strength |
|---|---|---|
| Batch processing | "each", "all", "every", iteration over a collection | Strong |
| Scoring or ranking | "score", "rank", "rate", "evaluate", "compare" | Strong |
| Statistics or aggregation | "count", "total", "average", "distribution", "summary" | Strong |
| Mandatory fields | "must include", "always include", "required", "ensure" | Moderate |
| Structured output | "format", "template", specific markdown/HTML structure | Moderate |
| Multiple data sources | Multiple distinct fetch operations identified | Moderate |
| Reproducibility | "daily", "recurring", "same as yesterday", "every morning" | Supportive |

If multiple strong signals are present, route directly to compiled mode. No further analysis needed.

If no signals are present, route directly to prompt mode.

If the signal is ambiguous, proceed to Stage 2.

**Stage 2: LLM cost estimation (small LLM call)**

For prompts that are not obviously one mode or the other, make a cheap classification call. The LLM is asked to estimate:

- How many items will be processed.
- Approximate tokens per item from each data source.
- Total context required if executed in prompt mode.
- Whether deterministic guarantees are required by the task.
- Recommended mode: prompt or compiled.

This classification call costs perhaps $0.01 in tokens. If it correctly routes a task to compiled mode that would have cost $2–3 in prompt mode, the return on that investment is 200–300x.

**Stage 3: User override (explicit or configured)**

The user can always override the automatic decision:

- Explicit instruction: "Compile this task" or "Just do it in chat."
- Task-level configuration: "Always compile job search tasks."
- Global preference: "Default to compiled mode for tasks involving more than 10 items."
- If a task has been compiled before and the generated program is cached, default to compiled mode for subsequent runs.

The three stages are ordered by cost: Stage 1 is free, Stage 2 is cheap, Stage 3 requires no computation at all. Most tasks will be resolved at Stage 1 — the structural signals in typical prompts are unambiguous.

### 7.4 Applied to the Job Search Example

The agent receives the job search prompt. Stage 1 pattern matching identifies:

- "search... for all JobServe emails" → batch processing (strong)
- "Score each job" → scoring (strong)
- "Exclude roles scoring below 5" → filtering with threshold (strong)
- "Summary Statistics" with counts and distributions → aggregation (strong)
- Detailed markdown format with anchor links → structured output compliance (moderate)
- Gmail + LinkedIn → multiple data sources (moderate)

Four strong signals and two moderate signals. The decision is unambiguous at Stage 1 — compiled mode — without spending a single token on cost estimation.

For comparison, consider "What's the weather in London tomorrow?" — no batch processing, no scoring, no statistics, no structured output, single data source. Zero signals. Prompt mode, resolved at Stage 1.

The grey area — where Stage 2 earns its keep — is something like "Find me three good restaurants near the office and explain why you chose them." Small batch (3 items), some evaluation, but likely manageable in context. Stage 2 would estimate ~3 items, ~500 tokens each, total ~2,000 tokens of data plus reasoning — well within prompt mode. Correct decision: prompt mode.

### 7.5 The Bootstrap Cost

Mode selection itself uses computational resources — at minimum, Stage 1 pattern matching, and potentially a Stage 2 LLM call. This is an irreducible bootstrap cost: spending tokens to decide whether to spend tokens.

This is analogous to a compiler deciding whether to apply an optimisation pass. The analysis cost is tiny compared to the execution cost difference between the two paths. A $0.01 classification call that prevents a $2.50 prompt-mode execution has a clear economic justification. Even if the classification is wrong occasionally, the expected value is strongly positive as long as the accuracy is reasonable.

The classification does not need to be perfect. The failure modes are asymmetric:

- **False positive (prompt task routed to compiled):** Unnecessary code generation overhead. The task still completes correctly, just with higher latency. Cost: perhaps $0.10–0.20 extra.
- **False negative (compiled task left in prompt mode):** The original problem — high token cost, constraint drift, unreliable statistics. Cost: $1–3 extra plus reliability degradation.

The penalty for false negatives is much higher than for false positives. The decision threshold should therefore lean toward compiled mode when uncertain.

---

## 8. Remaining Open Questions

### 8.1 Sandboxing and Trust

Generated code that calls real external services (reading email, posting to APIs) needs careful sandboxing:

- What permissions does the sandbox have?
- Can generated code only call registered MCP servers, or can it make arbitrary network calls?
- Should the agent present the generated code to the user for approval before execution?
- Should there be a dry-run mode that validates the code without executing external calls?

### 8.2 Error Recovery

What happens when generated code fails mid-execution?

- Does the agent retry with a patched version of the code?
- Does it fall back to prompt mode for the failing portion?
- How does it report partial results?

### 8.3 Code Quality and Review

Should the LLM review its own generated code before execution?

- A second LLM pass checking for obvious bugs, missing error handling, or incorrect MCP usage could catch many issues.
- This adds latency and token cost, but may be worth it for reliability.
- Alternatively, static analysis or schema validation of MCP calls could catch type mismatches without an LLM pass.

### 8.4 Caching and Reuse of Generated Programs

If the agent generates a program for "daily job search report" today, can it reuse or adapt that program tomorrow?

- This moves toward the pre-built runtime model — but with the runtime generated by the agent itself over time.
- A library of previously generated and validated programs could become a performance optimisation.
- Risk: cached programs may not adapt to changed MCP server schemas or user requirements.

---

## 9. Relationship to the White Paper Example

The engineering white paper (section 6) presents the job search report as a concrete example using the pre-built runtime model. This was chosen for clarity of exposition — it cleanly illustrates the separation of semantic reasoning from deterministic execution without introducing the additional complexity of code generation.

The hybrid MCP model with the `agent_mcp` client library described here is the intended general-purpose mechanism. The white paper example remains valid as an illustration of *what* compiled mode achieves (cost reduction, deterministic guarantees, reproducibility). This document explores *how* it achieves it in a general-purpose agent.

As this design matures, the white paper may be updated with a second example showing the MCP-based execution model, or a reference to this document may be added.

---

## 10. Summary of Current Thinking

The compiled task execution model for a general-purpose personal agent should:

1. **Use LLM-generated code** — not pre-built runtimes — to maintain generality.
2. **Program against registered MCP servers** — providing typed, known interfaces that constrain the generated code and reduce bug surface area.
3. **Access MCP servers via a client library (`agent_mcp`)** — the library handles registry lookup, process spawning, client connection, and credential passthrough. The LLM writes against a minimal API surface (`connect`, `call`) using the same server names and tool schemas it already knows from prompt mode.
4. **Keep bulk data out of context entirely** — the generated code fetches, processes, and outputs data without it ever entering the LLM's conversation history. The LLM only sees compact results when called back for narrative generation.
5. **Support per-item LLM calls for semantic operations** — operations like summarization, classification, or structured extraction that require language understanding are handled by bounded, independent LLM calls from generated code via `agent_llm`, not by loading all data into a single context. This preserves the cost and scalability benefits of compiled mode while supporting tasks that are not purely deterministic.
6. **Select execution mode via a three-stage decision pipeline** — structural pattern matching (free), LLM cost estimation (cheap), and user override. The decision threshold leans toward compiled mode when uncertain, because the cost of false negatives (prompt mode for a compiled task) is much higher than false positives (compiled mode for a prompt task).
7. **Execute in a sandbox** — with controlled access to MCP servers and appropriate permission boundaries.
8. **Remain inspectable** — generated code can be reviewed before execution.

Two companion libraries enable this model. `agent_mcp` bridges the agent's MCP server registry into generated code — same servers, same schemas, same credentials, accessible from both the agent loop (prompt mode) and generated programs (compiled mode). `agent_llm` provides bounded LLM access for semantic operations (summarization, classification, extraction) that cannot be reduced to deterministic code. Together they define the complete runtime environment for generated programs: data access via MCP, language understanding via LLM, and everything else in pure code.

---

## Design Evolution Log

| Date | Key Decision |
|---|---|
| Initial | Three execution models identified: pre-built runtime, fully dynamic, hybrid MCP |
| Initial | Hybrid MCP model selected as most promising direction |
| 2026-02-27 | "Agent loop fetches, code processes" approach rejected — data in context defeats the purpose |
| 2026-02-27 | MCP client library (`agent_mcp`) concept introduced — generated code spawns MCP servers directly |
| 2026-02-27 | MCP access from generated code resolved as a design question |
| 2026-02-27 | Three-stage mode selection framework designed: structural classification → LLM cost estimation → user override |
| 2026-02-27 | Asymmetric failure cost identified — threshold should lean toward compiled mode when uncertain |
| 2026-02-27 | LLM calls within compiled mode recognised — `agent_llm` companion library for per-item semantic operations (summarization, classification, extraction) |
| 2026-02-27 | Cost comparison revised with measured data — theoretical estimates understate prompt mode cost by ~5.6x; actual measurement: $0.79 for 50-email task vs ~$0.19 compiled (same tier), ~$0.04 compiled (Haiku) |

---

*This document will be updated as the design evolves.*