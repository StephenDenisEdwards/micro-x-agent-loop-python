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
- **Conditional registration:** Only available when Google credentials are configured

## Implementation

- Source: `src/micro_x_agent_loop/tools/gmail/gmail_send_tool.py`
- Constructs raw RFC 2822 message text
- Uses `base64.urlsafe_b64encode` for encoding
- Sends via `gmail.users().messages().send()`

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
