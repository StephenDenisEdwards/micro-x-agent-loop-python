# Job Search App - Implementation Notes

## Overview

This is a Python console application that:
- Searches Gmail for JobServe emails (last 24h)
- Searches LinkedIn for contract roles (last 24h)
- Scores all jobs against search criteria (1-10 scale)
- Generates a markdown report with Top 10, full specs, and statistics

**Key design principle:** Avoid LLM calls to minimize costs. Uses pure heuristic scoring instead.

## Architecture

### Core Modules

```
main.py              Entry point, orchestrates workflow
├── gmail_client.py  Placeholder Gmail access (upgradeable)
├── linkedin_client.py Placeholder LinkedIn access (upgradeable)
├── scoring.py       Heuristic-based scoring engine (no LLM)
└── report_generator.py Markdown report generation

mcp_client.py        Generic MCP stdio protocol client
gmail_client_mcp.py  Production Gmail access via MCP
linkedin_client_mcp.py Production LinkedIn access via MCP
```

### Execution Flow

```
main.py
  ↓
1. Load config + criteria
  ↓
2. Initialize Gmail client
   ↓ Search JobServe emails (last 24h)
   ↓ Extract job details via regex parsing
  ↓
3. Initialize LinkedIn client
   ↓ Search contract roles (multiple keyword passes)
   ↓ Fetch full job specs
  ↓
4. Score all jobs
   ↓ Technology match (30% weight)
   ↓ Seniority match (25% weight)
   ↓ Rate match (20% weight)
   ↓ Sector match (15% weight)
   ↓ Location match (10% weight)
   ↓ Bonuses (AI/ML, Healthcare, Outside IR35, Architecture)
  ↓
5. Filter jobs (5+/10 only)
  ↓
6. Generate report (staged file writes)
   ├─ Header
   ├─ Top 10 best matches
   ├─ JobServe section
   ├─ LinkedIn section
   └─ Summary statistics
```

## MCP Integration

### What is MCP?

MCP (Message Passing Protocol) is a stdio-based protocol for AI system communication. This app connects to MCP servers to access:
- **Gmail API** - Search and read emails
- **LinkedIn API** - Search and fetch job details

### Placeholder vs. Production

**Current state:** `gmail_client.py` and `linkedin_client.py` are placeholders (empty results)

**Production version:** Use `gmail_client_mcp.py` and `linkedin_client_mcp.py` which:
1. Initialize MCP clients via stdio
2. Send JSON requests to MCP servers
3. Parse structured responses
4. Handle errors gracefully

### Using MCP Clients

Update `main.py` to use MCP versions:

```python
from gmail_client_mcp import GmailClientMCP
from linkedin_client_mcp import LinkedInClientMCP

# In main():
gmail = GmailClientMCP(config)
gmail.connect()

linkedin = LinkedInClientMCP(config)
linkedin.connect()

# ... use normally ...

gmail.disconnect()
linkedin.disconnect()
```

### MCP Server Requirements

Requires running MCP servers:

```bash
# Gmail MCP server (example)
python -m mcp_gmail --port 9000

# LinkedIn MCP server (example)
python -m mcp_linkedin --port 9001
```

Or specify in `config.json`:

```json
{
  "mcp": {
    "gmail_command": "python mcp_gmail.py",
    "linkedin_command": "node mcp_linkedin.js"
  }
}
```

## Scoring Logic

### Weights

| Dimension | Weight | Notes |
|-----------|--------|-------|
| Technology | 30% | .NET, Azure, AI/ML, Python, etc. |
| Seniority | 25% | Senior/Lead/Architect roles valued |
| Rate | 20% | £500-700+/day preferred |
| Sector | 15% | Healthcare, Finance, Legal preferred |
| Location | 10% | London or Remote UK |
| **Bonuses** | +0.3 to +1.5 | AI/ML, Healthcare, Outside IR35, Architecture |

### Score Ranges

| Score | Category | Action |
|-------|----------|--------|
| 9-10 | Perfect | Apply immediately |
| 7-8 | Strong | High priority |
| 5-6 | Good | Worth considering |
| <5 | Weak | **Excluded** |

### Technology Scoring (Example)

- 0 tech matches → 2/10
- 1 match → 4/10
- 2 matches → 6/10
- 3 matches → 8/10
- 4+ matches → 10/10

### Seniority Scoring

Regex-based keyword detection:
- Contains "senior", "lead", "principal", "architect" → 10/10
- Contains "junior", "graduate", "entry level" → 2/10
- Unknown / mid-level → 6/10

## Email Parsing

### JobServe Email Structure

```
Subject: [Job Title] - [Company] - [Location]
Body:
  Rate: £XXX/day or £XXX-XXX/day
  Duration: X months/weeks
  IR35: Inside/Outside/Not specified
  [Full job specification]
```

### Extraction Patterns

**Rate:** `£([\d,\-]+)(?:\s*/\s*day|/d)?`

**Duration:** `(\d+\s*(?:months?|weeks?|days?))`

**Reference:** `(?:Ref|Reference)[:=]?\s*([A-Z0-9]+)` or `\b(JX\d+)\b`

**IR35:** Case-insensitive substring match for "outside ir35" or "inside ir35"

## Report Generation

### File Naming

Strictly follows format: `todays-jobs-YYYY-MM-DD.md`

- No versions: ~~`todays-jobs-2026-03-01-v1.md`~~ ❌
- No timestamps: ~~`todays-jobs-2026-03-01-01-30.md`~~ ❌
- Correct: `todays-jobs-2026-03-01.md` ✓

### Staged File Writing

To avoid token limits, writes in stages:

1. **write_file()** - Header + Top 10 section
2. **append_file()** - JobServe section
3. **append_file()** - LinkedIn section
4. **append_file()** - Summary statistics

### Top 10 Format

Two-line entries with HTML anchors:

```markdown
1. **[Job Title](#anchor-name)** - Score: 8/10
   £500-650/day, Remote UK, 6 months. .NET/Azure, microservices.
```

Anchor names generated from title:
- Lowercase
- Replace spaces/special chars with hyphens
- Max 50 chars
- Linked from detailed sections below via `<a id="anchor-name"></a>`

### Detailed Job Format

**JobServe:**
```
### Job Title
**Score: X/10**

**Location:** ...
**Rate:** £XXX/day
**Duration:** X months
**IR35:** Inside/Outside/Not specified
**Posted:** JobServe, Ref: ABC123

**Summary:**
[1 paragraph: role, tech, responsibilities]

**Links:**
- [Job Spec](url)
- [Apply](url)

**Why this score:**
[1 paragraph explaining score rationale]
```

**LinkedIn:**
```
### Company - Job Title
**Score: X/10**

**Company:** ...
**Location:** ...
**Type:** Contract - Remote
**Sector:** Healthcare
**Posted:** Posted X days ago

**Summary:**
[1 paragraph]

**Link:** [View Job](url)

**Why this score:**
[1 paragraph, bold major constraints]
```

### Summary Statistics

Includes:
- Total jobs found (JobServe + LinkedIn)
- Jobs scoring 5+/10
- Average score
- Top 8 technologies (with counts)
- All sectors mentioned
- Contract/Permanent split
- Location distribution
- IR35 status breakdown
- 5-7 key observations
- 5-6 recommended actions
- Generation timestamp

## Cost Optimization

### Why No LLM?

1. **Scoring** - Heuristic rules run in <1ms per job
2. **Email parsing** - Regex extraction is fast and deterministic
3. **Report generation** - Template-based markdown building
4. **Total cost** - Zero LLM API calls ✓

### When to Use LLM (Optional)

Could add LLM for:
- Smart summary generation from full specs (experimental)
- Salary negotiation hints
- Career progression suggestions
- Cover letter generation

But these are optional enhancements.

## Error Handling

### Graceful Degradation

- MCP server unavailable → Placeholder clients return empty results
- Email parsing errors → Skip bad emails, continue processing
- LinkedIn fetch timeout → Use partial results if available
- File write errors → Log and continue with remaining sections

### Logging

- INFO: Major milestones
- DEBUG: Job scoring details
- WARNING: Missing servers, skipped jobs
- ERROR: Parse failures, connection issues

## Future Enhancements

1. **Learning** - Track applied roles, adjust weights based on feedback
2. **Alerts** - Email notifications for 9-10 scoring roles
3. **Database** - SQLite cache of searched roles (avoid duplicates)
4. **Negotiation** - Rate prediction based on score and sector
5. **Cover letters** - Generate personalized letters per role
6. **Tracking** - Spreadsheet export with application status
7. **Parallel search** - Concurrent Gmail/LinkedIn queries
8. **Incremental** - Only search since last run (delta search)

## Testing

### Manual Testing

```bash
cd tools/job_search_2

# Dry run (no MCP servers needed)
python main.py

# Should produce: todays-jobs-YYYY-MM-DD.md
ls todays-jobs*.md
```

### With Mock Data

Modify `gmail_client.py` and `linkedin_client.py` to return test jobs:

```python
def search_jobserve_last_24h(self) -> List[Dict]:
    return [
        {
            'source': 'jobserve',
            'title': 'Senior .NET Architect',
            'company': 'Acme Corp',
            'location': 'London',
            'rate': '600',
            'duration': '6 months',
            'ir35': 'Outside IR35',
            'full_spec': '[...long spec...]',
        },
    ]
```

### Integration Testing

With real MCP servers:

```bash
# Terminal 1: Start MCP servers
mcp-gmail --stdio
mcp-linkedin --stdio

# Terminal 2: Run app
python main.py
```

## Configuration

### config.json

```json
{
  "gmail": {
    "enabled": true,
    "mcp_server": "gmail"
  },
  "linkedin": {
    "enabled": true,
    "mcp_server": "linkedin"
  },
  "search": {
    "jobserve_lookback_hours": 24,
    "linkedin_lookback_hours": 24,
    "min_score_threshold": 5
  },
  "output": {
    "directory": "../../../documents"
  }
}
```

### Environment Variables

```bash
export JOB_SEARCH_OUTPUT_DIR="/path/to/documents"
python main.py
```

## Deployment

### As Cron Job

```bash
# Run daily at 8 AM
0 8 * * * cd /path/to/tools/job_search_2 && python main.py
```

### As Docker Container

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
CMD ["python", "main.py"]
```

### As Scheduled Task (Windows)

```powershell
$action = New-ScheduledTaskAction -Execute "python" -Argument "C:\path\to\main.py"
$trigger = New-ScheduledTaskTrigger -Daily -At 08:00
Register-ScheduledTask -Action $action -Trigger $trigger -TaskName "JobSearch"
```

## Debugging

### Enable Debug Logging

```python
# In main.py
logging.basicConfig(level=logging.DEBUG)
```

### Inspect Intermediate Data

Add breakpoints or print statements:

```python
# After scoring
for job in scored_jobs:
    print(f"{job['title']}: {job['score']}")
```

### Test Scoring in Isolation

```python
from scoring import JobScorer

scorer = JobScorer({})
job = {'title': 'Test', 'full_spec': '.NET Azure microservices...'}
score = scorer.score_job(job)
print(f"Score: {score}")
```

## Performance Notes

- **Email parsing:** ~50ms per JobServe email
- **LinkedIn fetch:** ~500ms per job (API latency)
- **Scoring:** ~1ms per job (heuristic rules)
- **Report generation:** ~200ms (markdown building)
- **Total:** ~1-5 seconds for 10-30 jobs

Parallel MCP requests could improve LinkedIn fetch speed 2-3x.

## References

- [MCP Protocol Spec](https://spec.modular.com/mcp/)
- [Gmail API](https://developers.google.com/gmail/api)
- [LinkedIn Jobs API](https://www.linkedin.com/developers/)
- [Regex Cheat Sheet](https://cheatography.com/davechild/cheat-sheets/regular-expressions/)
