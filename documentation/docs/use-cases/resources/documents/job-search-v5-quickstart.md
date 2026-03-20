# Job Search v5 — Quick Start Guide

## Installation & Setup

### Prerequisites
- Python 3.10+
- `micro-x-agent-loop-python` repo cloned
- MCP servers configured (Google, LinkedIn)
- Environment: `.env` with required API keys

### Config Setup

Update `config.json` to include Google and LinkedIn MCP servers:

```json
{
  "McpServers": {
    "google": {
      "command": "python",
      "args": ["-m", "mcp.server.gmail"]
    },
    "linkedin": {
      "command": "python",
      "args": ["-m", "mcp.server.linkedin"]
    }
  },
  "WorkingDirectory": "./reports"
}
```

### Installation

1. Ensure you're in the project root:
   ```bash
   cd C:\Users\steph\source\repos\micro-x-agent-loop-python
   ```

2. Test the module:
   ```bash
   python test_job_search_v5.py
   ```
   
   Expected output:
   ```
   [SUCCESS] All tests passed!
   ```

## Basic Usage

### Run the Job Search

```bash
python -m tools.job_search_v5
```

### With Custom Config

```bash
python -m tools.job_search_v5 --config /path/to/custom-config.json
```

## Output

### Execution Log
```
[1/4] Collecting JobServe emails from past 24 hours...
  Found 12 JobServe emails
[2/4] Searching LinkedIn for senior contract roles...
  Found 34 LinkedIn jobs
[3/4] Scoring jobs...
  Scored 46 jobs, 18 scored 5+/10
[4/4] Generating markdown report...
  Created /path/to/todays-jobs-2026-03-01.md

✓ Report saved: todays-jobs-2026-03-01.md
  Top 10 matches, 18 jobs 5+/10, 12 JobServe + 34 LinkedIn
```

### Report File

**Location:** `WorkingDirectory/todays-jobs-YYYY-MM-DD.md`

**Sections:**
1. **Top 10 Best Matches** — Quick ranked list with scores and key reasons
2. **JobServe Jobs (24 Hours)** — Detailed breakdown of each email with score justification
3. **LinkedIn Jobs (24 Hours)** — Detailed breakdown with direct links
4. **Summary Statistics** — Tech counter, sector distribution, location breakdown, IR35 status, key observations, recommendations

### Example Report Filename
- `todays-jobs-2026-03-01.md` — Jobs collected on March 1, 2026
- `todays-jobs-2026-03-02.md` — Jobs collected on March 2, 2026

## Understanding the Scores

### Score Breakdown (0-10)

Each job is scored on:
- **Tech Stack (0-3 pts):** Matches to C#, .NET, Azure, Python, AI/ML, Docker, DevOps, etc.
- **Seniority (0-2 pts):** "Senior", "Lead", "Architect", "Principal" keywords
- **Rate (0-2 pts):** £500+ per day (£1 per £100 above minimum)
- **Sector (0-2 pts):** Healthcare, Finance, Legal, Industrial, Energy, Enterprise
- **Location (0-2 pts):** London, Remote UK, or nearby cities
- **IR35 Bonus (+1 pt):** "Outside IR35" status
- **Special Interest (+1 pt):** Healthcare, FHIR/HL7, regulatory, GDPR

### Example Score Calculation

**Job:** Senior .NET Engineer, Azure, Healthcare, London, £600/day, Outside IR35
- Tech (C#, .NET, Azure, AI/ML): 3 pts
- Seniority (Senior): 2 pts
- Rate (£600, above £500): 2 pts
- Sector (Healthcare): 2 pts
- Location (London): 2 pts
- IR35 Bonus: 1 pt
- Special (Healthcare): 1 pt
- **Total: 10/10** ✓ Top match!

**Job:** Junior Django Developer, £400/day, Startup, Location TBD
- Tech (Python): 1 pt
- Seniority (None): 0 pts
- Rate (£400, below £500): 0 pts
- Sector (None): 0 pts
- Location (Unknown): 0 pts
- **Total: 1/10** ✗ Filtered out (< 5)

## Interpreting the Report

### Top 10 Section
Lists the 10 highest-scoring jobs with:
- **Score:** 1-10 rating
- **Location:** Primary work location (London, Remote, Hybrid, City, etc.)
- **Rate:** Daily rate in GBP (if found)
- **Tech:** Top 3 matching technologies from your stack

**Example:**
```
1. **[Acme Corp - Senior .NET Architect](acme-corp-senior-net-architect)** - Score: 10/10
   London. £650/day. Tech: c#, azure, microservices.
```

### JobServe Section
Detailed breakdown of emails with:
- **Score:** 1-10 rating
- **Location:** Extracted from email body
- **Rate:** Extracted from email (if available)
- **Duration:** Contract length (months)
- **IR35:** Status (Outside/Inside/Not specified)
- **Why this score:** Justification (tech matches, location, rate, IR35)

### LinkedIn Section
Similar to JobServe, but includes:
- **Company name**
- **Direct link:** Click to view full job on LinkedIn
- **Job type:** Permanent/Contract (from posting)

### Statistics Section

**Key Metrics:**
- **Jobs Found:** Total count from both sources
- **Quality Jobs:** Count scoring 5+/10
- **Average Score:** Mean score of quality jobs
- **Tech Distribution:** Most-in-demand technologies (your stack analysis)
- **Sector Distribution:** Market breakdown (healthcare, finance, etc.)
- **Location Distribution:** Work location preference (London vs. Remote)
- **IR35 Status:** Contractor status (critical for tax planning)

**Key Observations:** Market insights based on today's data:
- Strong tech-stack alignment
- Sector trends (which sectors hiring?)
- Location trends (London saturation?)
- Rate trends (market rates moving?)

**Recommendations:** Prioritized actions:
1. Focus on top-scoring roles (8-10)
2. Check IR35 status carefully
3. Highlight sector matches (healthcare focus)
4. Consider emerging tech demand

## Common Scenarios

### No Jobs Found
- Check MCP server connections (Google, LinkedIn)
- Verify config.json has correct server settings
- Check .env for API keys
- Run `python test_job_search_v5.py` to diagnose

### Low Scores Across All Jobs
- Market may have fewer matches today
- Check if search keywords are current (LinkedIn searches use fixed keywords)
- Verify scoring criteria still align with your preferences
- Consider broadening sector or tech criteria

### All Jobs from One Source
- Other MCP server may not be connected
- Check console output for connection warnings
- Verify config.json includes both servers
- Validate API credentials

## Customization

### Changing Job Search Keywords

Edit `collector.py`, in `collect_linkedin_jobs()`:
```python
keywords = [
    "Senior .NET Engineer Azure",
    "Solution Architect C#",
    # ... add/change keywords here
]
```

### Adjusting Scoring Weights

Edit `scorer.py`:
- `CORE_TECHS`: Add/remove technologies or keywords
- `SENIORITY_KEYWORDS`: Adjust seniority detection
- `RATE_PREFERENCE_MIN/IDEAL`: Change rate thresholds
- `SECTORS`: Update sector priorities

### Changing Report Format

Edit `processor.py`:
- `generate_top_10()`: Modify ranking display
- `generate_statistics()`: Add custom metrics
- `_get_full_text()`: Change searchable fields

## Automation

### Daily Scheduled Run (Windows Task Scheduler)

1. Create batch file `job_search.bat`:
   ```batch
   @echo off
   cd C:\Users\steph\source\repos\micro-x-agent-loop-python
   python -m tools.job_search_v5
   ```

2. Schedule in Task Scheduler:
   - Trigger: Daily at 8:00 AM
   - Action: Run `job_search.bat`
   - Output: Check `reports/` directory for new files

### Email Results (Future)

Extend `__main__.py` to send report to your email:
```python
# After generating report
from tools.tools import gmail_send
await gmail_send(
    clients,
    to="stephen.denis.edwards@googlemail.com",
    subject=f"Jobs Report {today}",
    body="See attached markdown report..."
)
```

## Troubleshooting

### Module Import Error
```
ModuleNotFoundError: No module named 'job_search_v5'
```
**Solution:** Run from project root (`micro-x-agent-loop-python`)

### MCP Server Connection Failed
```
google: FAILED (error message)
```
**Solution:** Check config.json, verify API keys in .env

### File Permission Error
```
PermissionError: [Errno 13] Permission denied
```
**Solution:** Check WorkingDirectory exists and is writable

### Rate Extraction Failed
If rates aren't detected in HTML:
- Check email/HTML formatting
- May need to adjust regex in `scorer.py:extract_rate()`
- Currency conversion: EUR assumed at 0.84 GBP

## Next Steps

1. **Test with real data:** Run today and review report
2. **Fine-tune scoring:** Adjust weights based on your preferences
3. **Set up daily schedule:** Automate collection
4. **Track results:** Keep reports for trend analysis
5. **Extend collectors:** Add more job boards (WeWork, MRM, etc.)

## Support

- **Module tests:** `python test_job_search_v5.py`
- **Config validation:** Check `config.json` has McpServers section
- **Architecture docs:** See `job-search-v5-architecture.md`
- **Design decisions:** See `job-search-v5-summary.md`
