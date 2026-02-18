# Design: Map-Evaluate Pattern for Criteria Matching

## Status: Proposal (Draft)

## Problem

When the agent needs to evaluate N items against a set of criteria (e.g. matching
job specs against a search profile), the current approach processes everything within
a single conversation. This causes token accumulation:

```
Context = system_prompt
        + criteria document (~180 lines / ~2k tokens)
        + prompt template (~250 lines / ~3k tokens)
        + job_listing_1 full spec (~500-2000 tokens)
        + job_listing_2 full spec (~500-2000 tokens)
        + ...
        + job_listing_N full spec (~500-2000 tokens)
        + all intermediate reasoning
        + report output
```

With 15-20 items, this easily exceeds 50k+ tokens in the conversation history.
Quality degrades as earlier items fall out of the attention window, and the
conversation risks hitting context limits before the report is complete.

This is not specific to job matching — it applies to any "evaluate N items against
criteria" workflow: CV screening, document review, product comparison, compliance
checking, etc.

## Core Insight

The evaluation of each item against the criteria is **independent**. Item 5's score
doesn't depend on Item 3's content. Yet the current single-conversation approach
forces all items into shared context, wasting tokens on content that's irrelevant
to the item currently being evaluated.

## Proposed Solution: Map-Evaluate Tool

A new tool that implements a **map-reduce** pattern internally:

```
MAP phase:    For each item → isolated API call → structured score
REDUCE phase: Aggregate scored results → return compact summary to caller
```

The key architectural property: **the tool itself makes LLM calls**. Each inner
call has minimal context (just the rubric + one item), and only the compact
scored outputs flow back to the outer conversation.

### Token Budget Comparison

**Current approach** (single conversation, 10 jobs):
```
Outer context: ~5k (system + criteria + prompt)
+ 10 job specs: ~15k (avg 1500 tokens each)
+ 10 reasoning blocks: ~5k
+ report output: ~5k
= ~30k tokens in context, growing with each job
```

**Map-Evaluate approach** (isolated scoring, 10 jobs):
```
Each inner call: ~1k (rubric) + ~1.5k (one job) + ~0.3k (score output) = ~2.8k
× 10 calls = ~28k total tokens used across all calls
Outer context: ~5k (system + prompt) + ~3k (all 10 compact scores) + ~5k (report)
= ~13k tokens in outer context (never grows with item count)
```

The outer conversation stays lean regardless of how many items are evaluated.

## Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Outer Agent Loop (existing)                                │
│                                                             │
│  User prompt → Agent reads criteria → Agent fetches list    │
│       │                                                     │
│       ▼                                                     │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  evaluate_items tool                                  │   │
│  │                                                       │   │
│  │  Inputs:                                              │   │
│  │    - rubric (compact scoring criteria)                │   │
│  │    - items (list of {id, content} or {id, source})    │   │
│  │    - output_format (what to extract per item)         │   │
│  │                                                       │   │
│  │  ┌─────────────────────────────────────────────┐      │   │
│  │  │  MAP: For each item (parallel)              │      │   │
│  │  │                                             │      │   │
│  │  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  │      │   │
│  │  │  │ API call │  │ API call │  │ API call │  │      │   │
│  │  │  │ rubric + │  │ rubric + │  │ rubric + │  │      │   │
│  │  │  │ item_1   │  │ item_2   │  │ item_3   │  │      │   │
│  │  │  │  ↓       │  │  ↓       │  │  ↓       │  │      │   │
│  │  │  │ score_1  │  │ score_2  │  │ score_3  │  │      │   │
│  │  │  └──────────┘  └──────────┘  └──────────┘  │      │   │
│  │  └─────────────────────────────────────────────┘      │   │
│  │                                                       │   │
│  │  REDUCE: Aggregate → sort by score → format           │   │
│  │                                                       │   │
│  │  Returns: compact scored summary (not raw items)      │   │
│  └──────────────────────────────────────────────────────┘   │
│       │                                                     │
│       ▼                                                     │
│  Agent writes report from compact scores                    │
│  (never saw the raw item content)                           │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

**Phase 1: Preparation (outer agent)**
```
1. Agent reads criteria file → compiles to compact rubric (or uses pre-compiled)
2. Agent fetches item list (e.g. job listings with metadata)
3. Agent applies quick filters on metadata (exclude obvious mismatches)
4. Agent calls evaluate_items with rubric + surviving items
```

**Phase 2: Map-Evaluate (inside tool)**
```
5. For each item:
   a. If item has a source reference (URL/path), fetch the content
   b. Build a minimal prompt: rubric + item content + output schema
   c. Call Anthropic API (non-streaming, small max_tokens)
   d. Parse structured response
6. Aggregate all scores
7. Sort by score descending
8. Return formatted summary string
```

**Phase 3: Report (outer agent)**
```
9. Agent receives compact scored list (~3k tokens for 10+ items)
10. Agent writes report using scored summaries
11. Full raw item content was never in the outer conversation
```

### Quick-Filter (Phase 1 Optimisation)

Before calling evaluate_items, the agent can pre-filter using only listing
metadata (title, company, location, salary). This is a cheap heuristic pass:

```
Listing metadata only (no full spec fetch needed):
  - Title contains "Junior" or "Graduate" → EXCLUDE
  - Location not in accepted list → EXCLUDE
  - Salary below minimum → EXCLUDE
  - Required tech has zero overlap with profile → EXCLUDE
```

This reduces the number of items that need full spec fetching and LLM evaluation.
For job search: if 25 listings come back, quick-filter might reduce to 12-15,
saving 10+ unnecessary API calls.

## Detailed Design

### Scoring Rubric Format

A compact, structured representation of matching criteria. This replaces the
full-text criteria document in inner API calls.

```json
{
  "description": "Senior .NET/Azure contractor, London/Remote UK",
  "dimensions": [
    {
      "name": "tech_match",
      "weight": 3,
      "instruction": "Count matching technologies from must_have and nice_to_have lists",
      "must_have": [".NET Core", "C#", "Azure"],
      "nice_to_have": ["AI/ML", "Blazor", "Microservices", "Python", "Docker"]
    },
    {
      "name": "seniority",
      "weight": 2,
      "instruction": "Match against target seniority levels",
      "target": ["Senior", "Lead", "Architect", "Principal", "Staff"],
      "exclude": ["Junior", "Graduate", "Entry Level", "Intern"]
    },
    {
      "name": "rate",
      "weight": 2,
      "instruction": "Score based on day rate. 600+ ideal, 500+ acceptable, below 500 penalise",
      "ideal_min": 600,
      "acceptable_min": 500,
      "currency": "GBP"
    },
    {
      "name": "location",
      "weight": 2,
      "instruction": "Score based on location preference",
      "preferred": ["London", "Remote UK"],
      "acceptable": ["Hybrid UK", "South East England"],
      "penalise": ["Outside UK", "Relocation required"]
    },
    {
      "name": "contract_type",
      "weight": 1,
      "instruction": "Contract preferred, outside IR35 bonus. Permanent acceptable but lower score",
      "preferred": "contract",
      "ir35_bonus": "outside"
    },
    {
      "name": "sector",
      "weight": 1,
      "instruction": "Score based on sector interest",
      "preferred": ["Healthcare", "MedTech", "Finance", "FinTech", "Legal Tech"],
      "acceptable": ["Industrial", "Energy", "Enterprise SaaS", "RegTech"]
    },
    {
      "name": "special_interest",
      "weight": 1,
      "instruction": "Bonus for special interest areas",
      "interests": ["AI/ML integration", "Healthcare domain", "FHIR/HL7", "Regulatory/GDPR", "IoT"]
    }
  ],
  "score_range": {"min": 1, "max": 10},
  "exclude_below": 5
}
```

This is ~40 lines vs ~180 lines of free-text criteria. More importantly, it
gives the inner LLM calls a precise, unambiguous scoring framework rather than
expecting it to interpret prose.

### Tool Interface

```python
class EvaluateItemsTool:
    """
    Evaluates a list of items against a scoring rubric using isolated
    LLM calls. Each item is scored independently in its own API call,
    preventing token accumulation in the outer conversation.
    """

    name = "evaluate_items"

    description = (
        "Evaluate a list of items against a scoring rubric. Each item is "
        "scored independently using a separate LLM call, keeping the outer "
        "conversation context lean. Returns a ranked list of scored summaries. "
        "Use this when you need to score/rank multiple items (e.g. job specs, "
        "documents, candidates) against a set of criteria."
    )

    input_schema = {
        "type": "object",
        "properties": {
            "rubric": {
                "type": "object",
                "description": (
                    "Structured scoring rubric with weighted dimensions. "
                    "Each dimension has a name, weight, instruction, and "
                    "dimension-specific fields (thresholds, lists, etc.)"
                ),
            },
            "items": {
                "type": "array",
                "description": (
                    "Items to evaluate. Each item has an 'id' and either "
                    "'content' (inline text) or 'source' (URL or file path "
                    "to fetch). Prefer 'source' for large items to avoid "
                    "passing full content through the outer conversation."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "content": {"type": "string"},
                        "source": {"type": "string"},
                        "metadata": {
                            "type": "object",
                            "description": "Optional pre-extracted metadata (title, company, etc.)"
                        },
                    },
                    "required": ["id"],
                },
            },
            "output_fields": {
                "type": "array",
                "description": (
                    "Fields to extract per item beyond score. "
                    "E.g. ['summary', 'tech_matches', 'concerns', 'reasoning']"
                ),
                "items": {"type": "string"},
            },
            "concurrency": {
                "type": "integer",
                "description": "Max parallel API calls (default 3). Respect rate limits.",
            },
        },
        "required": ["rubric", "items"],
    }
```

### Inner Prompt Template

Each isolated evaluation call uses a minimal prompt:

```
System: You are a scoring engine. Evaluate the item below against the rubric.
Return ONLY valid JSON matching the output schema. No commentary.

Rubric:
{rubric_json}

Output schema:
{
  "score": <int 1-10>,
  "summary": "<one paragraph summary of the item>",
  "dimension_scores": {
    "<dimension_name>": <int 1-10>,
    ...
  },
  "reasoning": "<one paragraph explaining the score>",
  "extracted": {
    "<output_field>": "<value>",
    ...
  }
}

Item:
{item_content}
```

This prompt is ~200-400 tokens for the rubric + schema, plus the item content.
Total per call: typically under 3k tokens input, ~300 tokens output.

### Inner Call Configuration

The inner API calls should use conservative settings:

```python
# Inner evaluation call settings
EVAL_MODEL = "claude-sonnet-4-5-20250929"  # Fast, cheap, good at structured output
EVAL_MAX_TOKENS = 1024                     # Scores are compact
EVAL_TEMPERATURE = 0.0                     # Deterministic scoring
```

Using Sonnet (not Opus) for inner calls is deliberate — scoring against a
structured rubric doesn't need the most capable model, and Sonnet is faster
and cheaper. The outer agent (which does the nuanced report writing and
user interaction) can still be whatever model the user configures.

### Source Fetching

When items have `source` references instead of inline `content`, the tool
fetches them internally. This is where the LinkedIn/web fetching logic lives:

```python
async def _fetch_item_content(self, source: str) -> str:
    """Fetch item content from a URL or file path."""
    if source.startswith(("http://", "https://")):
        # HTTP fetch (reuse linkedin_job_detail scraping logic
        # or a generic HTML-to-text fetcher)
        return await self._fetch_url(source)
    else:
        # File path — read from disk
        return await self._read_file(source)
```

This means the outer agent can pass job URLs directly:

```json
{
  "items": [
    {"id": "job-1", "source": "https://linkedin.com/jobs/view/...", "metadata": {"title": "Senior .NET Dev", "company": "Acme"}},
    {"id": "job-2", "source": "https://linkedin.com/jobs/view/...", "metadata": {"title": "Lead Architect", "company": "Widget Corp"}},
  ]
}
```

The full job spec text is fetched inside the tool, passed to the inner LLM call,
scored, and then **discarded**. Only the compact score object comes back.

### Concurrency Control

```python
async def _evaluate_all(self, rubric, items, output_fields):
    semaphore = asyncio.Semaphore(self._concurrency)  # default 3

    async def evaluate_one(item):
        async with semaphore:
            content = item.get("content") or await self._fetch_item_content(item["source"])
            return await self._score_item(rubric, content, item, output_fields)

    results = await asyncio.gather(
        *(evaluate_one(item) for item in items),
        return_exceptions=True,
    )
    # Filter errors, sort by score descending
    scored = [r for r in results if not isinstance(r, Exception)]
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored
```

Concurrency of 3 balances speed against API rate limits. With 10 items at
~2 seconds per inner call, total wall-clock time is ~7 seconds (vs ~20 seconds
sequential).

### Return Format

The tool returns a formatted string (conforming to the Tool protocol) that the
outer agent uses for report writing:

```
## Evaluation Results (10 items scored, 8 above threshold)

1. **Senior C#/.NET Engineer (Blazor) - Medical Devices** — Score: 9/10
   Tech: .NET Core, Blazor, MQTT | Location: Limerick (onsite) | Rate: €500/day
   Summary: Exceptional Blazor/medical device role combining core strengths...
   Concerns: Ireland location requires relocation, rate below target

2. **OrganOx - Windows Software Engineer** — Score: 8/10
   Tech: C#/.NET 6-8, Azure IoT, MQTT | Location: Oxford (hybrid) | Rate: £80-100k perm
   Summary: Safety-critical medical device software with strong domain match...
   Concerns: Permanent role, not contract

...

### Excluded (below threshold):
- Golang Python Developer (4/10) — Primary Golang focus, technology mismatch
- API Automation Engineer (4/10) — Java test automation, wrong stack
```

This is ~150-200 tokens per item vs ~500-2000 tokens for the raw job spec.
For 10 items, that's ~2k tokens in the outer context instead of ~15k.

## Integration with Existing Architecture

### Fits the Tool Protocol

The evaluate_items tool implements the existing `Tool` protocol:

```python
class EvaluateItemsTool:
    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def input_schema(self) -> dict[str, Any]: ...
    async def execute(self, tool_input: dict[str, Any]) -> str: ...
```

No changes needed to `Agent`, `AgentConfig`, `llm_client`, or the tool protocol.

### Constructor Dependencies

The tool needs an Anthropic API client for inner calls:

```python
class EvaluateItemsTool:
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5-20250929"):
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._concurrency = 3
```

Registered in `tool_registry.py` like any other tool, receiving the API key
that's already available there.

### Rubric File Convention

For repeated use cases (like daily job search), store the rubric as a JSON file
alongside the criteria:

```
resources/documents/
  search-criteria.txt        ← existing human-readable criteria
  search-rubric.json         ← compiled scoring rubric (new)
  search-prompt.txt          ← existing prompt template
```

The outer agent reads `search-rubric.json` and passes it as the `rubric` parameter.
Alternatively, the agent can compile the rubric on-the-fly from `search-criteria.txt`
on first use, then the user can refine and save it.

## Workflow: Job Search (Concrete Example)

### Current Flow (token-heavy)

```
Turn 1: User sends prompt
Turn 2: Agent reads search-criteria.txt (180 lines → context)
Turn 3: Agent reads search-prompt.txt (250 lines → context)
Turn 4: Agent searches Gmail → 9 emails (summaries → context)
Turn 5: Agent reads email 1 full content → context
Turn 6: Agent reads email 2 full content → context
...
Turn 13: Agent reads email 9 → context
Turn 14: Agent searches LinkedIn → 15 listings (summaries → context)
Turn 15: Agent fetches job detail 1 → context
Turn 16: Agent fetches job detail 2 → context
...
Turn 29: Agent fetches job detail 15 → context
Turn 30: Agent scores all jobs in-context (all specs still in history)
Turn 31: Agent writes report section 1
Turn 32: Agent writes report section 2
...

Context at turn 30: ~50-80k tokens (all specs accumulated)
Total API input tokens across all turns: ~200k+
```

### New Flow (map-evaluate)

```
Turn 1: User sends prompt
Turn 2: Agent reads search-rubric.json (~40 lines → context)
Turn 3: Agent reads search-prompt.txt (report format only → context)
Turn 4: Agent searches Gmail → 9 email subjects + snippet metadata
Turn 5: Agent searches LinkedIn → 15 listing titles + metadata
Turn 6: Agent quick-filters on metadata → 12 candidates survive
Turn 7: Agent calls evaluate_items(rubric=..., items=[12 source refs])
         ├── Inner call 1: fetch job spec + score → {score: 9, summary: ...}
         ├── Inner call 2: fetch job spec + score → {score: 8, summary: ...}
         ├── ...  (12 calls, 3 concurrent, ~8 seconds wall clock)
         └── Inner call 12: score → {score: 4, summary: ...}
         Tool returns: compact ranked list (~2k tokens)
Turn 8: Agent writes report section 1 (Top 10 from scored list)
Turn 9: Agent appends report section 2 (JobServe details from scored list)
Turn 10: Agent appends report section 3 (LinkedIn details from scored list)
Turn 11: Agent appends report section 4 (Summary statistics)

Context at turn 7: ~8k tokens (rubric + metadata + compact scores)
Total API input tokens: ~40k (12 inner calls × ~3k) + ~30k (outer turns)
= ~70k total vs ~200k+ before
```

### Token Savings Summary

| Metric                         | Current     | Map-Evaluate |
|-------------------------------|-------------|--------------|
| Peak outer context            | ~50-80k     | ~8-13k       |
| Total input tokens (all calls)| ~200k+      | ~70k         |
| Risk of context overflow      | High        | Low          |
| Items evaluable per run       | ~15-20 max  | ~50+ feasible|
| Quality at item N             | Degrades    | Consistent   |

## Generalisation

This pattern is not specific to job matching. The same tool handles any
"evaluate N items against criteria" workflow:

| Use Case              | Rubric                    | Items                  | Source         |
|-----------------------|---------------------------|------------------------|----------------|
| Job matching          | Skills/rate/location prefs| Job spec URLs          | LinkedIn/email |
| CV screening          | Job requirements          | CV file paths          | Local files    |
| Document review       | Quality/compliance rules  | Document paths/URLs    | Files/web      |
| Product comparison    | Feature requirements      | Product page URLs      | Web            |
| Code review triage    | Coding standards          | PR diff URLs           | GitHub API     |
| Vendor evaluation     | Selection criteria        | Proposal file paths    | Local files    |

The rubric format is flexible — dimensions can have any structure as long as
the inner prompt can interpret them. The `instruction` field in each dimension
is the key: it tells the inner LLM how to score that dimension for the item.

## Open Questions

1. **Rubric compilation**: Should the tool accept free-text criteria and compile
   the rubric internally, or always require a pre-structured rubric? Pre-structured
   is more token-efficient but less ergonomic for one-off use.

2. **Source fetcher extensibility**: Currently handles URLs and file paths. Should
   it support pluggable fetchers (e.g. Gmail message IDs, GitHub PR numbers)?
   This would let it directly consume the output of gmail_search without a
   separate gmail_read step.

3. **Caching**: If the same item is evaluated against different rubrics (or the
   same rubric is refined), should fetched content be cached? Disk cache with
   TTL would avoid re-fetching the same LinkedIn job spec.

4. **Streaming feedback**: The outer agent is blocked while inner calls run.
   Should the tool emit progress to stderr (e.g. "Scored 3/12 items...")?

5. **Inner model selection**: Should this be configurable per-call, or fixed?
   Some rubrics might benefit from a more capable model (e.g. nuanced healthcare
   compliance assessment) while simple tech-match scoring works fine with Haiku.

6. **Threshold in tool vs outer agent**: The rubric specifies `exclude_below: 5`.
   Should the tool filter before returning, or return everything and let the
   outer agent decide? Filtering in the tool saves tokens; returning everything
   gives the agent more flexibility.

## Implementation Phases

### Phase 1: Core evaluate_items tool
- EvaluateItemsTool class conforming to Tool protocol
- Inner API calls with structured JSON output
- URL and file path source fetching
- Concurrency control with asyncio.Semaphore
- Register in tool_registry

### Phase 2: Rubric compiler
- A helper (or separate tool) that takes free-text criteria and produces
  a structured rubric JSON
- One-time compilation, result saved to disk for reuse

### Phase 3: Source fetcher plugins
- Abstract the fetch logic so new source types can be added
- Gmail message fetcher, GitHub PR fetcher, etc.

### Phase 4: Caching and observability
- Disk-based content cache with TTL
- Progress reporting to stderr
- Token usage tracking for inner calls
