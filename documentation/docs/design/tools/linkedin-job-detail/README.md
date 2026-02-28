# Tool: linkedin_job_detail

Fetch the full job description from a LinkedIn job URL.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | Yes | The LinkedIn job URL (from a `linkedin_jobs` search result) |

## Behavior

- Fetches the full job page and extracts the description
- Returns: title, company, location, and the full job description text
- Uses `html_to_text()` to convert the HTML description to readable plain text with preserved link URLs

## Implementation

- Server: `mcp_servers/ts/packages/linkedin/src/tools/linkedin-job-detail.ts`
- Uses HTTP client for async requests
- Parses with `cheerio`
- Multiple CSS selector fallbacks for title, company, location, and description elements
- HTML-to-text conversion for job descriptions

## Example

```
you> Get the full description for that first job
```

Claude calls:
```json
{
  "name": "linkedin_job_detail",
  "input": {
    "url": "https://www.linkedin.com/jobs/view/1234567890"
  }
}
```

## Limitations

- LinkedIn may return different page layouts (A/B testing)
- IP-based blocking after many requests
- Some job pages require login to view full details
