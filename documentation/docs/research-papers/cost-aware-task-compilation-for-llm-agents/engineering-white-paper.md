# LLM as Task Compiler  
## A Cost-Aware Execution Architecture for General-Purpose Agents

### Executive Summary

General-purpose LLM agents frequently attempt to solve large, structured, or compliance-sensitive tasks entirely within a single prompt context. While this approach works for small, conversational tasks, it becomes economically inefficient and reliability-fragile as task size and structural constraints increase.

This paper proposes a practical architectural shift: treat the LLM not as the execution engine, but as a **semantic task compiler**. When task characteristics indicate high token cost, deterministic requirements, or compliance sensitivity, the agent should switch from prompt-based reasoning to programmatic execution. The LLM generates task specifications, rubrics, and extraction logic; a runtime executes deterministic processing; and the LLM returns only to produce narrative output from compact, structured results.

This separation of semantic reasoning from deterministic execution enables lower token cost, stronger reliability guarantees, and improved scalability in real-world agent systems.

---

## 1. The Limitation of Prompt-Centric Execution

Modern LLM systems advertise large context windows, but context expansion does not eliminate fundamental economic and architectural constraints. Transformer attention scales quadratically with sequence length, increasing computational cost and latency. More importantly, large prompts dilute instruction salience and leave constraint compliance probabilistic rather than guaranteed.

Consider a task such as ranking 20 job postings against a rubric and producing a structured report that includes mandatory application links. Executed naïvely in prompt space, this task requires injecting all job content into context, reasoning over it, and generating structured output. Token cost grows linearly with data size while attention cost grows superlinearly. Compliance constraints such as “include a link for each job” remain vulnerable to omission.

In practice, expanding context windows postpones but does not solve these problems. The limitation is not merely memory size; it is architectural.

---

## 2. The Executive Control Gap

LLMs simulate reasoning effectively, but they do not instantiate persistent executive control. They optimize next-token likelihood rather than goal completion under constraints. They do not natively maintain durable task objects, audit compliance deterministically, or optimize for economic efficiency across multi-step execution.

This becomes operationally significant in structured batch tasks. Without an external executive layer, the model must:

- Hold all working data in prompt space.
- Track constraints probabilistically.
- Perform ranking and validation within a single forward pass.
- Risk forgetting low-salience requirements.

The result is cost inflation and reliability drift.

---

## 3. The Core Insight

Not all tasks should be executed in prompt space.

Tasks involving large batches, deterministic scoring, mandatory field enforcement, reproducibility requirements, or external data retrieval are structurally better suited to programmatic execution. In these cases, the LLM should act as a semantic planner that compiles the task into an executable pipeline.

This approach introduces three execution modalities:

- **Prompt Mode** for small, low-risk tasks.
- **Retrieval Mode** for moderately scoped tasks requiring iterative narrowing.
- **Compiled Task Mode** for large, structured, or compliance-sensitive workloads.

The innovation is not the use of code itself, but the deliberate, cost-aware switching between modalities.

---

## 4. Cost-Aware Modality Switching

Execution mode selection can be guided by a simple cost model.

Estimated prompt-mode cost:

C_prompt ≈ B + N × T_item + T_reason + T_output

Where:
- B is base instruction cost,
- N is item count,
- T_item is average tokens per item,
- T_reason is reasoning overhead,
- T_output is report length.

Estimated compiled-mode cost:

C_program ≈ T_rubric + N × T_extract + T_report

If C_prompt significantly exceeds C_program, or if reliability constraints are present, the system should switch to Compiled Task Mode.

This transforms economic efficiency from an incidental property into an explicit architectural decision.

---

## 5. Compiled Task Mode Architecture

In Compiled Task Mode, responsibilities are separated:

**The LLM generates:**
- A structured task specification.
- A rubric interpretation.
- A normalized extraction schema.
- Validation rules.
- A report template.

**The runtime executes:**
- Data acquisition from external sources.
- Field extraction and normalization.
- Deterministic scoring and sorting.
- Constraint validation (e.g., link inclusion).
- Artifact generation.

**The LLM returns to:**
- Produce a concise narrative summary using compact, structured data.

The LLM no longer carries the entire working set in context. Deterministic logic moves outside token space.

---

## 6. Concrete Example: Job Search Report Generation

To make the architecture tangible, consider a real-world agent task: a daily job search agent that retrieves contract job postings from Gmail (JobServe alerts) and LinkedIn, scores each against a detailed personal rubric, and produces a structured markdown report with ranked results, per-job analysis, and summary statistics.

The user prompt specifies a weighted scoring rubric (technology match, seniority, rate, sector, location, IR35 status), a minimum score threshold, a precise markdown output format with anchor links between a top-10 summary and detailed entries, mandatory fields per job (links, rate, location), and computed summary statistics including technology frequency counts, sector distribution, and market observations.

### 6.1 Prompt Mode: What Happens Today

The agent attempts the entire task in context:

1. Calls Gmail tool — retrieves 30+ full JobServe emails, each 500–2,000 tokens of raw HTML and text.
2. Calls LinkedIn search — retrieves 20+ job listings with full descriptions.
3. The context now contains approximately 50,000 or more tokens of raw job data alongside the original instructions and scoring rubric.
4. The LLM must simultaneously hold the scoring rubric in attention, score each job, rank them, enforce the exact markdown format, include every application link, generate working anchor tags, and compute aggregate statistics.

The failure modes are predictable and systemic:

- **Links are omitted.** Low-salience constraints like "include one link per item" compete with 50,000 tokens of job content for attention weight. Some entries silently lose their application URLs.
- **Statistics are wrong.** The model performs mental arithmetic over dozens of items. "Total Jobs Found: 23 (15 JobServe + 8 LinkedIn)" may report 14 + 8 = 23. Counts for technology frequency, sector distribution, and IR35 status are approximate at best.
- **Rankings are inconsistent.** Without a deterministic scoring function, the same job set scored twice may produce different orderings.
- **Cost is high.** The entire raw dataset occupies context for the full generation. At typical API pricing, each run costs $2–3 in token consumption.

These are not occasional edge cases. They are structural consequences of executing a batch-processing workload inside a probabilistic text generator.

### 6.2 Compiled Task Mode: The Three-Phase Approach

**Phase 1 — The LLM Compiles the Task (semantic work)**

The LLM reads the user prompt and produces a structured task specification rather than the report itself:

```json
{
  "task_type": "batch_score_and_report",
  "data_sources": [
    {
      "type": "gmail",
      "query": "from:jobserve newer_than:1d",
      "extract": "full_body"
    },
    {
      "type": "linkedin",
      "query": "(.NET OR Azure OR AI/ML) contract UK",
      "extract": "full_details"
    }
  ],
  "extraction_schema": {
    "title": "string",
    "company": "string",
    "location": "string",
    "rate": "string",
    "duration": "string",
    "ir35_status": "enum(inside, outside, not_specified)",
    "contract_type": "enum(contract, permanent, not_specified)",
    "sector": "string",
    "technologies": ["string"],
    "seniority": "string",
    "apply_url": "string",
    "spec_url": "string",
    "source": "enum(jobserve, linkedin)",
    "posted": "string"
  },
  "scoring_rubric": {
    "technology_match":  {"weight": 0.25, "core": [".NET Core", "Azure", "AI/ML", "Blazor", "Python", "Microservices"]},
    "seniority_match":   {"weight": 0.15, "preferred": ["Senior", "Lead", "Architect"]},
    "rate_match":        {"weight": 0.20, "ideal_min": 600, "acceptable_min": 500},
    "sector_match":      {"weight": 0.15, "preferred": ["Healthcare", "Finance", "Legal", "Industrial"]},
    "location_match":    {"weight": 0.10, "preferred": ["London", "Remote UK"]},
    "ir35_bonus":        {"weight": 0.05, "bonus": "outside"},
    "special_interest":  {"weight": 0.10, "keywords": ["AI/ML", "Healthcare", "FHIR", "HL7", "Regulatory"]}
  },
  "filter": {"min_score": 5},
  "output": {
    "format": "markdown",
    "template": "todays-jobs-report",
    "filename": "todays-jobs-2026-02-27.md"
  }
}
```

The LLM also performs per-item **semantic extraction** — interpreting messy email HTML and unstructured job descriptions into clean structured records conforming to the schema above. This is where the model adds genuine value: understanding that "Hybrid — 2 days London office" maps to `location: "London (Hybrid)"`, or that a job mentioning "Azure Functions, Cosmos DB, Event Grid" maps to `technologies: ["Azure", "Microservices"]`. Each extraction is a small, focused call against a single job's content — typically 100–300 tokens of output per item.

**Phase 2 — The Runtime Executes Deterministically (no LLM needed)**

The runtime receives the structured records and task specification, then performs all batch processing in code:

```python
# Score each job deterministically against the compiled rubric
for job in jobs:
    job.score = compute_weighted_score(job, rubric)

# Filter below threshold
qualified = [j for j in jobs if j.score >= 5]

# Sort deterministically
ranked = sorted(qualified, key=lambda j: j.score, reverse=True)
top_10 = ranked[:10]

# Validate constraints — every job must have at least one link
for job in qualified:
    assert job.apply_url or job.spec_url, f"Missing link: {job.title}"

# Compute statistics exactly
stats = {
    "total": len(qualified),
    "by_source": Counter(j.source for j in qualified),
    "avg_score": mean(j.score for j in qualified),
    "top_technologies": Counter(
        t for j in qualified for t in j.technologies
    ).most_common(8),
    "sectors": Counter(j.sector for j in qualified),
    "contract_vs_perm": Counter(j.contract_type for j in qualified),
    "locations": Counter(j.location for j in qualified),
    "ir35": Counter(j.ir35_status for j in qualified),
}

# Render report from template using the exact markdown format
render_report(top_10, jobserve_jobs, linkedin_jobs, stats,
              template="todays-jobs-report")
```

Every count is exact. Every link is validated before the report is written. The ranking is reproducible — the same input always produces the same output.

**Phase 3 — The LLM Returns for Narrative (small, focused calls)**

The LLM is called back only for the parts that require semantic reasoning:

- **Per-job "Why this score" paragraph** — given the compact structured record (approximately 100 tokens per job), not the full job specification.
- **Key Observations** — given the computed statistics, write 5–7 market trend insights.
- **Recommended Actions** — given the top 10 ranked records, write prioritised advice.

Each call receives only the data it needs. The model never holds the full dataset in context.

### 6.3 Cost and Reliability Comparison

| Dimension | Prompt Mode | Compiled Task Mode |
|---|---|---|
| Data in context | ~50,000+ tokens (all raw jobs) | ~200 tokens per extraction call |
| Scoring method | Probabilistic, single pass | Deterministic, weighted formula in code |
| Link inclusion | May silently omit some | Validated — guaranteed present |
| Statistics accuracy | Approximate mental arithmetic | Exact computation |
| Total token cost | ~60,000–80,000 tokens (~$2–3) | ~15,000–20,000 tokens (~$0.50–0.75) |
| Reproducibility | Different rankings on repeated runs | Identical output every time |

The LLM touches this task three times: to compile the specification, to extract structured data from unstructured source content, and to write narrative prose from compact results. Everything between those steps is deterministic code. The expensive and unreliable part — holding 50,000 tokens of raw data in context while simultaneously enforcing formatting constraints, computing statistics, and maintaining scoring consistency — is eliminated entirely.

---

## 7. Deterministic Guarantees

Compiled Task Mode enables guarantees that prompt-only execution cannot reliably provide:

- Exact item counts.
- Mandatory field enforcement.
- Link inclusion validation.
- Reproducible ranking.
- Structured output conformance.

Constraint satisfaction becomes deterministic rather than probabilistic.

---

## 8. Practical Benefits

This architecture provides:

- Significant token cost reduction.
- Reduced hallucination probability.
- Improved compliance reliability.
- Better economic predictability.
- Clear separation of concerns.
- Enterprise-ready execution guarantees.

It mirrors the pattern already visible in robust systems such as code interpreters and coding agents, which externalize deterministic execution to compilers, runtimes, or test suites.

---

## 9. Risks and Trade-Offs

This approach introduces trade-offs:

- Over-triggering compiled mode may increase latency.
- Code execution must be sandboxed.
- DSL design may introduce brittleness.
- System complexity increases.
- Mode selection policy must remain simple and deterministic.
- **MCP protocol constraint:** The data sources accessed via MCP servers return unstructured text content blocks, not structured JSON. The per-item semantic extraction described in Section 6.2 Phase 1 requires LLM calls to interpret this text into structured records. This is acknowledged in the design (line 184: "interpreting messy email HTML") but the constraint is deeper than anticipated — it is inherent to the MCP specification and applies to all third-party MCP servers, not just email. See [ADR-014](../../architecture/decisions/ADR-014-mcp-unstructured-data-constraint.md) for the full analysis.

However, these risks are engineering challenges, not conceptual flaws.

---

## 10. Strategic Implications

Future LLM agents should not rely solely on larger context windows. Instead, they should orchestrate multiple computational substrates and dynamically select execution strategies based on cost, structure, and reliability requirements.

This reframes the LLM as a semantic planner embedded within a broader executive compute system.

Intelligence remains in semantic interpretation and narrative generation. Determinism, state persistence, and constraint enforcement belong in runtime.

---

## 11. Conclusion

Expanding context windows does not resolve economic and reliability constraints in structured agent tasks. By separating semantic reasoning from deterministic execution and introducing cost-aware modality switching, general-purpose agents can achieve greater scalability, stronger compliance guarantees, and predictable economic performance.

The LLM becomes not the execution engine, but the compiler of task-specific computation.

This shift represents a practical step toward robust, economically sustainable AI agent systems.