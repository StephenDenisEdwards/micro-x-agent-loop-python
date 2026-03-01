# Job Search Console App (Cheap Mode)

Hardcoded orchestration job search that connects to MCP servers directly and uses a single Haiku API call for scoring and report generation.

## Usage

```bash
python -m tools.job_search
```

Run from the project root. Requires `.env` with `ANTHROPIC_API_KEY`.

## How It Works

1. **Connect** to Google and LinkedIn MCP servers via stdio
2. **Collect** JobServe emails from Gmail (last 24h) + LinkedIn jobs (multiple keyword searches)
3. **Score** all jobs against criteria using a single Claude Haiku 4.5 API call
4. **Write** markdown report to `C:\Users\steph\source\repos\resources\documents\todays-jobs-YYYY-MM-DD.md`

## Cost Comparison

| Approach | LLM Calls | Model | Est. Cost |
|----------|-----------|-------|-----------|
| Agent loop (Sonnet) | 8-15+ | claude-sonnet-4-5 | $0.50-2.00+ |
| Agent loop (Haiku) | 8-15+ | claude-haiku-4-5 | $0.10-0.40 |
| **This app** | **1** | **claude-haiku-4-5** | **$0.03-0.07** |

## Architecture

```
tools/job_search/
├── __main__.py     # Entry point: connect MCP servers, collect data, score, write output
├── mcp_client.py   # Lightweight MCP stdio client (connect/call_tool/close)
├── collector.py    # Gmail + LinkedIn data collection orchestration
├── scorer.py       # Single Haiku API call for scoring + report generation
└── README.md       # This file
```

## Dependencies

Uses packages already in the project: `mcp`, `anthropic`, `python-dotenv`.
