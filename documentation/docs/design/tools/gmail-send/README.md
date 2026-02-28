# Tool: gmail_send

Send a plain-text email from the authenticated Gmail account.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `to` | string | Yes | Recipient email address |
| `subject` | string | Yes | Email subject line |
| `body` | string | Yes | Email body (plain text) |

## Behavior

- Composes a MIME message with `Content-Type: text/plain; charset=utf-8`
- Encodes the message as base64url and sends via the Gmail API
- Returns the sent message ID on success
- **Availability:** Requires Google credentials in the `google` MCP server's `env` config

## Implementation

- Server: `mcp_servers/ts/packages/google/src/tools/gmail-send.ts`
- Uses `googleapis` for Gmail API access
- Constructs RFC 2822 message and base64url encodes
- Sends via Gmail API `messages.send`

## Example

```
you> Send an email to alice@example.com saying I'll be late to the meeting
```

Claude calls:
```json
{
  "name": "gmail_send",
  "input": {
    "to": "alice@example.com",
    "subject": "Running late",
    "body": "Hi Alice,\n\nI'll be about 15 minutes late to the meeting.\n\nThanks"
  }
}
```

## Authentication

Same OAuth2 flow as other Gmail tools. See [gmail_search](../gmail-search/README.md) for authentication details.
