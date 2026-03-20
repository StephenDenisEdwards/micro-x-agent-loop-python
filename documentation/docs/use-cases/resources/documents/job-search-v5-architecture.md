# Job Search v5 — Architecture & Design Decisions

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Job Search v5 Console App                      │
│                      (python -m tools.job_search_v5)               │
└─────────────────────────────────────────────────────────────────┘
                                  │
                ┌─────────────────┼─────────────────┐
                ▼                 ▼                 ▼
        ┌───────────────┐  ┌───────────────┐  ┌─────────────┐
        │  __main__.py  │  │  config.json  │  │  .env       │
        │               │  │  (MCP servers)│  │ (API keys)  │
        │ - Config load │  └───────────────┘  └─────────────┘
        │ - MCP connect │
        │ - Orchestrate │
        └───────────────┘
                │
    ┌───────────┴───────────┐
    ▼                       ▼
┌──────────────────┐  ┌──────────────────┐
│  collector.py    │  │  scorer.py       │
│                  │  │                  │
│ collect_jobserve │  │ score_job()      │
│ collect_linkedin │  │ score_and_rank() │
└──────────────────┘  │ extract_*()      │
    ▲                 └──────────────────┘
    │                        ▲
    │ Gmail, LinkedIn         │ Pure Python
    │ MCP Servers             │ Keyword Matching
    │                         │
    └─────────────────────────┘
                │
                ▼
        ┌──────────────────┐
        │  processor.py    │
        │                  │
        │ generate_*()     │
        │ (all f-strings)  │
        └──────────────────┘
                │
                ▼
        ┌──────────────────┐
        │ Markdown Report  │
        │                  │
        │ todays-jobs-     │
        │ YYYY-MM-DD.md    │
        └──────────────────┘
```

## Data Flow

```
EMAIL (Gmail)           LINKEDIN API
      │                      │
      └──────────┬───────────┘
                 ▼
        Async Collection
        - collect_jobserve_emails()
          - Gmail search: from:jobserve.com newer_than:1d
          - Read full email bodies
          - Extract to standardized dict
        
        - collect_linkedin_jobs()
          - Search: 5 keywords × senior contract filter
          - Batch detail fetches (5 at a time)
          - Extract description + URL
                 │
                 ▼
        Job List (Raw)
        [{source, title, company, location, ...}, ...]
                 │
                 ▼
        Pure Python Scoring
        - score_job() on each job
        - Filter >= 5
        - Rank by score descending
        - Add metadata (tech_matches, sector, rate, IR35)
                 │
                 ▼
        Scored Job List
        [{..., score, tech_matches, ir35_status, ...}, ...]
                 │
                 ▼
        Markdown Generation
        - Header (title, date)
        - Top 10 with anchors
        - JobServe detail section
        - LinkedIn detail section
        - Statistics + observations
                 │
                 ▼
        File I/O (Staged)
        - write_file() header
        - append_file() top 10
        - append_file() jobserve
        - append_file() linkedin
        - append_file() stats
                 │
                 ▼
        Output: todays-jobs-YYYY-MM-DD.md
```

## Scoring Algorithm

**Max Score:** 10 points

### Technology Matching (0-3 points)
Count of core technologies found in job posting:
- 1 match: +1 point
- 2 matches: +2 points
- 3+ matches: +3 points (max)

**Tech Categories:**
- **C#/.NET:** c#, csharp, .net core, .net 6, .net 7, .net 8, .net 9, .net 10, aspnet, asp.net
- **Azure:** azure, azure services, azure functions, service bus, cosmos db, azure iot, azure ai
- **AI/ML:** ai, ml, machine learning, llm, langchain, openai, azure openai, rag, vector db, gpt, genai
- **Microservices:** microservices, event-driven, cqrs, event sourcing
- **Python:** python
- **Blazor:** blazor, webassembly, wasm
- **Docker:** docker, containers, kubernetes
- **DevOps:** devops, ci/cd, azure devops, github actions, pipelines
- **React:** react, next.js
- **Angular:** angular

### Seniority Level (0-2 points)
- Keyword match (senior, lead, architect, principal, staff engineer, head of): **+2 points**
- Fallback to "developer" or "engineer" without senior qualifier: **+1 point**
- No match: **0 points**

### Daily Rate (0-2 points)
- Extract via regex: £XXX, £XXX-YYY/day, €XXX
- EUR converted to GBP (×0.84)
- If rate ≥ £600 (ideal): **+2 points**
- If rate ≥ £500 (minimum): **+1 point**
- No rate found: **0 points**

### Sector Alignment (0-2 points)
Count of preferred sectors mentioned:
- 1 sector: +1 point
- 2+ sectors: +2 points (max)

**Sector Keywords:**
- **Healthcare:** healthcare, medtech, medical device, fhir, hl7, health data, clinical
- **Finance:** finance, fintech, banking, payments, investment
- **Legal:** legal, legal tech, legaltech
- **Industrial:** industrial, manufacturing
- **Energy:** energy, oil, gas, utility
- **Enterprise:** enterprise, saas, platform

### Location Preference (0-2 points)
- Match London, Remote, or UK: **+2 points**
- City match (Coventry, Milton Keynes, Oxford, etc.): **+1 point**
- No match: **0 points**

### IR35 Status (Bonus +1 point)
- "outside ir35" found in text: **+1 bonus point**
- Inside IR35 or unspecified: **0 points**

### Special Interests (Bonus +1 point)
Healthcare domain keywords (healthcare, fhir, hl7, medical device, regulatory, gdpr): **+1 bonus point**

### Exclusion Rules
**Score = 0 if:**
- "junior", "graduate", "intern", "entry level" found in text

## Key Design Decisions

### 1. Zero LLM Calls
**Decision:** All scoring is pure Python keyword matching and regex.

**Rationale:**
- No Claude API cost (token efficiency)
- Faster execution (no network latency)
- 100% reproducible (no sampling)
- Fully transparent heuristics (auditable)
- Can run offline with cached job data

**Trade-offs:** Less semantic understanding than LLM-based scoring, but acceptable given the keyword-dense nature of job postings.

### 2. Keyword-Based Tech Detection
**Decision:** Hard-coded CORE_TECHS dict with exact keyword lists per technology.

**Rationale:**
- No NLP required
- Stephen's stack is well-defined (job search criteria doc)
- Keywords are reliable indicators (job descriptions use standard terminology)
- Easy to update/maintain

**Trade-offs:** Won't catch semantic variants (e.g., "machine learning" spelled as "ML/AI"), but rare in formal job postings.

### 3. Staged File Writing
**Decision:** Create file with header, then append_file for each section.

**Rationale:**
- Avoids building huge in-memory string
- Handles potential token limits in future (if sections become large)
- Mirrors best practice for large file generation
- Easy to add/remove sections

**Implementation:**
```python
write_file("todays-jobs-2026-03-01.md", generate_header(...))
append_file("todays-jobs-2026-03-01.md", generate_top_10(...))
append_file("todays-jobs-2026-03-01.md", generate_jobserve_jobs(...))
append_file("todays-jobs-2026-03-01.md", generate_linkedin_jobs(...))
append_file("todays-jobs-2026-03-01.md", generate_statistics(...))
```

### 4. Report Filename Format
**Decision:** `todays-jobs-YYYY-MM-DD.md` (no version, no time)

**Rationale:**
- Date-based uniqueness (one report per calendar day)
- Easy to find today's jobs: `todays-jobs-2026-03-01.md`
- Alphabetically sortable
- No confusion with semantic versioning

### 5. Collector Architecture
**Decision:** Separate async functions for JobServe and LinkedIn with different collection logic.

**Rationale:**
- **JobServe:** Collect emails from Gmail, parse full body
  - Source 1: Email subject line (high-level job info)
  - Source 2: Email body (detailed spec)
  - One-to-one email-to-job mapping
  
- **LinkedIn:** API search + batch detail fetch
  - Source 1: Search results (title, company, location, posted date, salary snippet)
  - Source 2: Full job detail page (complete description)
  - Batch fetches in groups of 5 to avoid rate limits

### 6. Metadata Extraction Functions
**Decision:** Separate extractors for tech, sector, location, IR35 (vs. baking into scorer).

**Rationale:**
- Scorer focuses on scoring logic (clean responsibility)
- Extractors are reusable (stats generation, future filtering)
- Easy to test extraction logic independently
- Extensible (add new extractors for skills, seniority level, etc.)

### 7. Statistical Summary
**Decision:** Counters for tech, sector, location; separate IR35 status count.

**Rationale:**
- Tech counter shows market demand (what's hot)
- Sector counter shows opportunity distribution
- Location counter validates search scope
- IR35 status matters to Stephen (contracts inside/outside)
- Identifies trends across day's jobs

### 8. Repository Structure
**Decision:** Job search as standalone tool under `tools/job_search_v5/`.

**Rationale:**
- Modular, reusable
- Can be invoked independently: `python -m tools.job_search_v5`
- Follows pattern of `tools/template`
- Minimal dependencies (only MCP client + standard lib)

## Error Handling

### Collection Phase
- **Gmail not connected:** Warning printed, continue with LinkedIn only
- **LinkedIn not connected:** Warning printed, continue with JobServe only
- **Both disconnected:** Empty job list, empty report

### Scoring Phase
- **Invalid job dict:** Skipped (no exception thrown)
- **Missing fields:** Graceful defaults ("Not specified", empty strings)

### Report Generation
- **Large job count:** Handled by staged file writing
- **Missing metadata:** Handled in processor functions with fallbacks

### File I/O
- **Output directory missing:** Created automatically
- **File write fails:** Exception raised to caller (caller handles)

## Performance Characteristics

### Time Complexity
- **Collection:** O(J) where J = total jobs collected (linear, async)
- **Scoring:** O(J × K) where K = avg keywords per job (linear)
- **Report generation:** O(J) to build strings + O(1) file I/O

### Space Complexity
- **In-memory jobs:** O(J × S) where S = avg job dict size (~5KB)
- **Markdown report:** O(J × R) where R = avg report lines per job (~20 lines)
- **Total:** ~5-10MB for 1000 jobs

### Network I/O
- **JobServe:** 1 Gmail search + N email reads (N ≤ 100)
- **LinkedIn:** 5 keyword searches + M detail fetches (M ≤ 75, batched)
- **Total:** ~6-10 network calls, moderate latency

## Testing Strategy

### Unit Tests (Per Module)
1. **scorer.py**
   - Test score_job() with known good/bad jobs
   - Verify rate extraction (£, €)
   - Verify tech/sector/location extraction
   - Edge cases: missing fields, malformed text

2. **processor.py**
   - Test markdown generation (format, anchors)
   - Test statistics calculation
   - Test edge cases: empty job list, single job

### Integration Tests
1. End-to-end with mock data
2. Compare output against reference report (`todays-jobs-2026-02-16-v1.md`)
3. Verify file creation and formatting

### Manual Tests
1. Run against real Gmail/LinkedIn (production)
2. Inspect top 10 scores (sanity check)
3. Verify report readability in Markdown viewer

## Future Enhancements

### Short Term
- Add WeWork, MRM, other job board parsers (similar collector pattern)
- Deduplication (same job posted to multiple sources)
- Rate comparison across sources

### Medium Term
- Store historical reports for trend analysis
- Automated email alerts for high-score jobs
- Integration with apply workflow (track applications)

### Long Term
- ML-based scoring (learn from Stephen's feedback)
- Negotiation hints (rate trending, market saturation)
- Contractor network intelligence (co-contractor recommendations)
