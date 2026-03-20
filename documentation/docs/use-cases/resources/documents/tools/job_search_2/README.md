# Job Search Console App

A Python console application that searches for contract roles on JobServe and LinkedIn, scores them against Stephen Edwards' job search criteria, and generates a markdown report.

## Features

- **No LLM calls** - Uses heuristic-based scoring to reduce costs
- **MCP integration** - Connects to Gmail and LinkedIn via Message Passing Protocol (stdio)
- **Dual-source search** - Combines JobServe emails and LinkedIn job listings
- **Heuristic scoring** - Technology, seniority, rate, sector, location matching (1-10 scale)
- **Markdown reports** - Generates detailed reports with Top 10, full job specs, and statistics

## Architecture

```
main.py              - Entry point, orchestrates flow
config.py            - Configuration loader
gmail_client.py      - Gmail/JobServe email search via MCP
linkedin_client.py   - LinkedIn job search via MCP
scoring.py           - Heuristic-based job scoring engine
report_generator.py  - Markdown report generation
```

## Setup

### Prerequisites
- Python 3.10+
- MCP servers running for Gmail and LinkedIn access
- Job search criteria in `documents/job-search-criteria.txt`

### Installation

```bash
cd tools/job_search_2
pip install -r requirements.txt
```

### Configuration

Edit `config.json` to set:
- MCP server endpoints
- Output directory
- Search parameters

## Usage

```bash
python main.py
```

The app will:
1. Search Gmail for JobServe emails from last 24 hours
2. Extract job details from email content
3. Search LinkedIn for matching contract roles
4. Score all jobs (1-10) against criteria
5. Filter to jobs scoring 5+/10
6. Generate `todays-jobs-YYYY-MM-DD.md` in documents directory

## Scoring Logic

Jobs are scored across 5 dimensions with weighted factors:

| Factor | Weight | Criteria |
|--------|--------|----------|
| **Technology** | 30% | Match to core stack (.NET, Azure, AI/ML, etc.) |
| **Seniority** | 25% | Senior/Lead/Architect roles preferred |
| **Rate** | 20% | £500-700+/day preferred |
| **Sector** | 15% | Healthcare, Finance, Legal, Industrial preferred |
| **Location** | 10% | London or Remote UK |

**Bonuses:**
- +0.5 for AI/ML focus
- +0.5 for Healthcare domain
- +0.5 for Outside IR35
- +0.3 for architecture/design leadership

**Score ranges:**
- 9-10: Perfect match
- 7-8: Strong match
- 5-6: Good match
- <5: Excluded

## Output Format

Generated markdown file includes:
1. **Top 10 Best Matches** - Ranked list with 2-line summaries
2. **JobServe Jobs** - Full specs with scores and explanations
3. **LinkedIn Jobs** - Full specs with scores and explanations
4. **Summary Statistics** - Tech stack distribution, location, IR35 status, observations

## Design Decisions

### No LLM Calls
- Scoring uses pure regex/keyword matching
- Eliminates cost and latency of LLM calls
- Provides deterministic, reproducible results

### MCP Integration
- Gmail and LinkedIn accessible via stdio-based MCP servers
- Allows direct API access without browser automation
- Extensible architecture for additional data sources

### Heuristic Scoring
- Simple rule-based matching against criteria
- Fast execution (< 1 second for 100 jobs)
- Transparent scoring logic
- Weights can be easily adjusted

## Files Structure

```
tools/job_search_2/
├── main.py                 # Entry point
├── config.py              # Configuration
├── config.json            # Config file
├── gmail_client.py        # Gmail integration
├── linkedin_client.py     # LinkedIn integration
├── scoring.py             # Scoring engine
├── report_generator.py    # Report generation
├── requirements.txt       # Dependencies
└── README.md             # This file
```

## Future Enhancements

- [ ] Implement full MCP stdio connections for Gmail/LinkedIn
- [ ] Add contract negotiation hints based on scoring
- [ ] Email notifications for high-scoring roles
- [ ] Persistent database of searched roles
- [ ] Learning from feedback (adjust weights based on applied roles)
- [ ] LinkedIn scraping for additional context
- [ ] Email alerts to recruiter contacts

## Notes

- The `gmail_client.py` and `linkedin_client.py` have placeholder MCP connections
- Full implementation requires active MCP servers running on target systems
- Report file naming follows strict format: `todays-jobs-YYYY-MM-DD.md` (no versions)
- Minimum score threshold is 5/10 (roles below excluded from report)
