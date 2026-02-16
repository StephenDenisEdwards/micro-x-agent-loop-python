# Tool: linkedin_jobs

Search for job postings on LinkedIn.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `keyword` | string | Yes | Job search keyword (e.g. `"software engineer"`) |
| `location` | string | No | Job location (e.g. `"New York"`, `"Remote"`) |
| `dateSincePosted` | string | No | Recency filter: `"past month"`, `"past week"`, or `"24hr"` |
| `jobType` | string | No | Employment type: `"full time"`, `"part time"`, `"contract"`, `"temporary"`, `"internship"` |
| `remoteFilter` | string | No | Work arrangement: `"on site"`, `"remote"`, or `"hybrid"` |
| `experienceLevel` | string | No | Level: `"internship"`, `"entry level"`, `"associate"`, `"senior"`, `"director"`, `"executive"` |
| `limit` | string | No | Max number of results (default `"10"`) |
| `sortBy` | string | No | Sort order: `"recent"` or `"relevant"` |

## Behavior

- Scrapes LinkedIn's public guest jobs API
- Returns a formatted list with: title, company, location, date posted, salary, and URL
- No authentication required

## Implementation

- Source: `src/micro_x_agent_loop/tools/linkedin/linkedin_jobs_tool.py`
- Uses `httpx.AsyncClient` for async HTTP requests
- Parses response HTML with `BeautifulSoup` + `lxml`
- Uses a browser-like User-Agent header

## Example

```
you> Find remote Python developer jobs posted in the last week
```

Claude calls:
```json
{
  "name": "linkedin_jobs",
  "input": {
    "keyword": "Python developer",
    "remoteFilter": "remote",
    "dateSincePosted": "past week"
  }
}
```

## Limitations

- LinkedIn may rate-limit or block scraping requests
- HTML structure changes can break CSS selectors
- No login-based features (saved jobs, recommendations)
