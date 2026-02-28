# Tool: gmail_search

Search Gmail using Gmail's native search syntax.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Gmail search query (e.g. `"is:unread"`, `"from:boss@co.com newer_than:7d"`) |
| `maxResults` | number | No | Max number of results (default 10) |

## Behavior

- Uses the Gmail API `messages.list` endpoint with the query
- Returns a formatted list with: message ID, date, from, subject, and snippet
- The message ID can be used with `gmail_read` to fetch the full content
- **Availability:** Requires `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in the `google` MCP server's `env` config

## Implementation

- Server: `mcp_servers/ts/packages/google/src/tools/gmail-search.ts`
- Uses `googleapis` for Gmail API access
- Fetches metadata headers (From, Subject, Date) for each result
- OAuth2 via unified Google auth module

## Example

```
you> Search my Gmail for unread emails from the last 3 days
```

Claude calls:
```json
{
  "name": "gmail_search",
  "input": {
    "query": "is:unread newer_than:3d",
    "maxResults": 10
  }
}
```

## Gmail Search Syntax

| Query | Description |
|-------|-------------|
| `is:unread` | Unread emails |
| `from:someone@example.com` | From a specific sender |
| `subject:meeting` | Subject contains "meeting" |
| `newer_than:7d` | From the last 7 days |
| `has:attachment` | Emails with attachments |
| `label:important` | Emails with the "important" label |

## Authentication

On first use, a browser window opens for Google OAuth sign-in. Tokens are cached in `.gmail-tokens/token.json` for future sessions. See [Getting Started](../../operations/getting-started.md) for setup instructions.
