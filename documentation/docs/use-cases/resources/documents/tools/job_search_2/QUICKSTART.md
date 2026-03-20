# Quick Start Guide

## Installation

```bash
cd tools/job_search_2
pip install -r requirements.txt
```

## Running the App

### Option 1: Dry Run (No MCP Servers)

Currently uses placeholder clients (returns empty results for testing):

```bash
python main.py
```

Will create: `C:\Users\steph\source\repos\resources\documents\todays-jobs-2026-03-01.md`

### Option 2: Production (With MCP Servers)

To use real Gmail and LinkedIn data:

1. **Update imports in main.py:**

```python
# Replace:
from gmail_client import GmailClient
from linkedin_client import LinkedInClient

# With:
from gmail_client_mcp import GmailClientMCP
from linkedin_client_mcp import LinkedInClientMCP
```

2. **Start MCP servers** (in separate terminals):

```bash
# Terminal 1: Gmail MCP server
mcp-gmail --stdio

# Terminal 2: LinkedIn MCP server  
mcp-linkedin --stdio
```

3. **Run the app:**

```bash
python main.py
```

## File Structure

```
tools/job_search_2/
├── main.py                  ← Entry point
├── config.py               ← Config loader
├── config.json             ← Configuration
├── gmail_client.py         ← Placeholder Gmail client
├── gmail_client_mcp.py     ← Production Gmail client
├── linkedin_client.py      ← Placeholder LinkedIn client
├── linkedin_client_mcp.py  ← Production LinkedIn client
├── mcp_client.py           ← Generic MCP protocol handler
├── scoring.py              ← Heuristic job scoring
├── report_generator.py     ← Markdown report generation
├── requirements.txt        ← Dependencies
├── README.md              ← Full documentation
├── IMPLEMENTATION_NOTES.md ← Technical deep dive
└── QUICKSTART.md          ← This file
```

## Key Features

✓ **No LLM calls** - Pure heuristic scoring saves costs  
✓ **MCP integration** - Direct API access via stdio  
✓ **Dual-source** - JobServe emails + LinkedIn jobs  
✓ **Smart scoring** - 5-factor weighted algorithm  
✓ **Rich reports** - Top 10, full specs, statistics  

## Output

Generates: `todays-jobs-YYYY-MM-DD.md` with:

1. **Top 10 Best Matches** - Ranked by score
2. **JobServe Section** - Full job specs from emails
3. **LinkedIn Section** - Full job specs from web
4. **Summary Statistics** - Tech distribution, locations, IR35 status

Example scores:
- 9-10: Perfect match (apply immediately)
- 7-8: Strong match (high priority)
- 5-6: Good match (worth considering)
- <5: Excluded

## Configuration

Edit `config.json`:

```json
{
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

## Scoring Weights

| Factor | Weight |
|--------|--------|
| Technology | 30% |
| Seniority | 25% |
| Rate | 20% |
| Sector | 15% |
| Location | 10% |
| Bonuses | +0.3 to +1.5 |

Bonuses for: AI/ML, Healthcare, Outside IR35, Architecture roles.

## Troubleshooting

### App runs but no jobs found

- **Gmail MCP:** Check if server is running (`mcp-gmail --stdio`)
- **LinkedIn MCP:** Check if server is running (`mcp-linkedin --stdio`)
- **Dry run:** Placeholder clients intentionally return empty results

### No output file created

- Check `config.json` output directory exists
- Verify write permissions on documents folder
- Enable DEBUG logging: `logging.basicConfig(level=logging.DEBUG)`

### MCP connection errors

1. Verify servers are running in separate terminals
2. Check MCP server command in config matches actual servers
3. Ensure servers support required methods (gmail_search, linkedin_jobs)

## Next Steps

1. **Test with placeholder clients** (no setup needed)
2. **Set up MCP servers** (see documentation)
3. **Update imports** to use production clients
4. **Configure config.json** with your parameters
5. **Schedule as cron/scheduled task** for daily runs

## Documentation

- **README.md** - Complete feature documentation
- **IMPLEMENTATION_NOTES.md** - Technical architecture and design decisions
- **scoring.py** - Scoring algorithm source code
- **report_generator.py** - Report generation logic

## Tips

1. **Adjust weights** in `scoring.py` if scoring doesn't match your preferences
2. **Add keywords** to `_extract_technologies()` for niche tech stacks
3. **Customize report** layout in `report_generator.py`
4. **Set min_score_threshold** to exclude low-quality jobs
5. **Enable logging** for debugging: `logging.basicConfig(level=logging.DEBUG)`

Enjoy! 🚀
