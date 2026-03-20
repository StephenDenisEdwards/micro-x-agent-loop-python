# Job Search v5 Implementation Summary

**Date:** March 1, 2026  
**Location:** `micro-x-agent-loop-python/tools/job_search_v5/`  
**Status:** Complete and ready to test

## Overview

**job_search_v5** is a Python console tool that collects job listings from two sources (Gmail/JobServe and LinkedIn), scores them using pure Python heuristics (no LLM), and generates a professional markdown report.

## Files Created

### Core Business Logic
- **`collector.py`** — Async job collection
  - `collect_jobserve_emails(clients)` → Searches Gmail for `from:jobserve.com` in past 24h, reads full email bodies
  - `collect_linkedin_jobs(clients, keywords)` → Searches LinkedIn for senior contract roles, fetches full job descriptions

- **`scorer.py`** — Pure Python scoring (no MCP, no LLM)
  - `score_job(job, source)` → Returns 1-10 score based on:
    - Tech match (0-3 points): C#/.NET, Azure, AI/ML, Microservices, Python, Blazor, Docker, DevOps
    - Seniority (0-2): Senior, Lead, Architect, Principal keywords
    - Rate (0-2): £500-700+/day preference
    - Sector (0-2): Healthcare, Finance, Legal, Industrial, Energy
    - Location (0-2): London, Remote UK
    - IR35 bonus (+1): Outside IR35 status
    - Special interests (+1): Healthcare domain, FHIR/HL7, regulatory, GDPR
  - `score_and_rank(jobs)` → Scores all, filters ≥5, returns sorted by score
  - `extract_tech_mentions()`, `extract_sector_mentions()`, `extract_location()`, `get_ir35_status()` → Metadata extraction

- **`processor.py`** — Markdown report generation (all f-strings, no LLM)
  - `generate_header(report_date)` → Title section
  - `generate_top_10(jobs)` → Ranked top 10 with HTML anchors and summaries
  - `generate_jobserve_jobs(jobs)` → Detailed JobServe section with score breakdowns
  - `generate_linkedin_jobs(jobs)` → Detailed LinkedIn section
  - `generate_statistics(all_jobs, filtered_jobs)` → Statistics including tech/sector/location/IR35 counters, key observations, recommendations

### Support Files (from template)
- **`mcp_client.py`** — MCP server connection and tool calling
- **`llm.py`** — Anthropic Claude API helpers (not used in this tool but included for completeness)
- **`tools.py`** — Typed wrappers for Gmail, LinkedIn, and web MCP tools
- **`__main__.py`** — Orchestration: config loading, MCP connection, task execution, file output
- **`__init__.py`** — Package marker

## Key Features

### Zero Cost (No LLM Calls)
- All scoring and report generation is pure Python
- No Claude API calls, no token costs
- Operates entirely on heuristic keyword matching and regex

### Intelligent Scoring
- Comprehensive tech stack matching (8 core technology categories)
- Seniority level detection
- Daily rate extraction (GBP and EUR with conversion)
- Sector classification
- Location preference matching
- IR35 status detection
- Special interest bonus (healthcare domain, FHIR/HL7, regulatory experience)

### Professional Markdown Report
- **Filename:** `todays-jobs-YYYY-MM-DD.md` (exact format, no version suffixes)
- **Sections:**
  1. Top 10 best matches with anchor links
  2. JobServe jobs (24 hours) — detailed breakdown with score justification
  3. LinkedIn jobs (24 hours) — detailed breakdown with score justification
  4. Summary statistics including:
     - Tech counter (top 8)
     - Sector distribution
     - Contract vs permanent split
     - Location distribution
     - IR35 status breakdown
     - Key observations (5-7 insights about market trends)
     - Recommended actions (5-6 prioritized next steps)

### Staged File Writing
Per requirements:
- `write_file()` creates the file with header + Top 10
- `append_file()` adds JobServe section
- `append_file()` adds LinkedIn section
- `append_file()` adds Statistics

## Configuration

The tool uses the standard config.json setup from `micro-x-agent-loop-python`:
- Reads `McpServers` config for Google and LinkedIn MCP servers
- Reads `WorkingDirectory` for output path
- Supports `--config` CLI flag

## Usage

```bash
# From project root
python -m tools.job_search_v5

# With custom config
python -m tools.job_search_v5 --config /path/to/config.json
```

## Output

```
[1/4] Collecting JobServe emails from past 24 hours...
  Found N JobServe emails
[2/4] Searching LinkedIn for senior contract roles...
  Found M LinkedIn jobs
[3/4] Scoring jobs...
  Scored X jobs, Y scored 5+/10
[4/4] Generating markdown report...
  Created /path/to/todays-jobs-2026-03-01.md

✓ Report saved: todays-jobs-2026-03-01.md
  Top 10 matches, Y jobs 5+/10, N JobServe + M LinkedIn
```

## Testing Checklist

- [ ] Verify MCP servers (Google, LinkedIn) connect successfully
- [ ] Check JobServe email parsing (full body content)
- [ ] Verify LinkedIn search with multiple keywords
- [ ] Validate scoring accuracy (spot-check 3-5 jobs)
- [ ] Confirm markdown file format (no version numbers in filename)
- [ ] Check anchor links in Top 10 section
- [ ] Verify statistics counters (tech, sector, location)
- [ ] Run report on known good data and compare formatting

## Design Principles

1. **No LLM Required:** Pure Python makes the tool cheap, fast, reliable
2. **Keyword-Based Scoring:** Matches Stephen's job criteria without semantic understanding
3. **Transparent Heuristics:** All scoring logic in `scorer.py` is visible and auditable
4. **Markdown First:** Direct report generation without templating overhead
5. **Staged Writing:** Large file written in sections to avoid token limits

## Future Enhancements

- Add WeWork, MRM, or other job board parsers
- Extend sector matching with domain-specific keywords
- Add role title normalization (e.g., "Engineer" → "Engineer")
- Implement job deduplication (same role posted to multiple sources)
- Add "Apply" link extraction and automation hooks
