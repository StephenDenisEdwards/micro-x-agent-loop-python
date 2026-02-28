# Tool: gmail_read

Read the full content of a Gmail email by its message ID.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `messageId` | string | Yes | The Gmail message ID (from `gmail_search` results) |

## Behavior

- Fetches the full message using the Gmail API
- Returns: From, To, Date, Subject, and the full email body
- Email body is returned as **raw HTML** for the LLM to parse directly (see [ADR-004](../../architecture/decisions/ADR-004-raw-html-for-gmail.md))
- For multipart messages, prefers HTML content over plain text
- Recursive MIME parsing handles nested multipart structures
- **Availability:** Requires Google credentials in the `google` MCP server's `env` config

## Implementation

- Server: `mcp_servers/ts/packages/google/src/tools/gmail-read.ts`
- Uses `googleapis` for Gmail API access
- Recursive MIME body extraction, prefers HTML over plain text
- Base64url decoding for message bodies

## Example

```
you> Read the first email from those search results
```

Claude calls:
```json
{
  "name": "gmail_read",
  "input": {
    "messageId": "18e1a2b3c4d5e6f7"
  }
}
```

## Design Decision

Raw HTML is passed to the LLM rather than converting to plain text. This preserves links, formatting, and structure that would be lost in text conversion. The LLM is capable of parsing HTML directly. See [ADR-004: Raw HTML for Gmail](../../architecture/decisions/ADR-004-raw-html-for-gmail.md) for the full rationale.
