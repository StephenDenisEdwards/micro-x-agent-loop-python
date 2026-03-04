# Tool: linkedin_draft_article

Create a draft LinkedIn article share (link post with preview card) for review before publishing.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | Yes | URL of the article to share |
| `title` | string | Yes | Article title for the share card (max 200 chars) |
| `description` | string | Yes | Article description for the share card (max 500 chars) |
| `commentary` | string | No | Optional commentary text above the article card (max 3000 chars) |
| `visibility` | string | No | `"PUBLIC"` (default) or `"CONNECTIONS"` |

## Behavior

- Validates the URL format and input lengths, builds a LinkedIn article share payload
- Does **not** call the LinkedIn API — stores the payload as a draft
- Returns a `draft_id` and human-readable preview showing the article card
- The draft must be published via `linkedin_publish_draft` within 10 minutes
- **Availability:** Only registered when `LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET` are set

## Implementation

- Server: `mcp_servers/ts/packages/linkedin/src/tools/draft-article.ts`
- Draft store: `mcp_servers/ts/packages/linkedin/src/draft-store.ts`
- Auth: `mcp_servers/ts/packages/linkedin/src/auth/linkedin-auth.ts`

## Example

```
you> Share my latest blog post on LinkedIn: https://dev.to/myuser/building-agent-loops
```

Claude calls:
```json
{
  "name": "linkedin_draft_article",
  "input": {
    "url": "https://dev.to/myuser/building-agent-loops",
    "title": "Building Agent Loops in Python",
    "description": "A practical guide to building minimal AI agent loops with Claude and MCP tools.",
    "commentary": "Just published a deep dive on building agent loops. Here's what I learned about keeping them minimal and reliable.",
    "visibility": "PUBLIC"
  }
}
```

Returns:
```json
{
  "draft_id": "b2c3d4e5-...",
  "preview": "[LinkedIn Article Share — PUBLIC]\n\nJust published a deep dive...\n\n📎 Building Agent Loops in Python\n   A practical guide...\n   https://dev.to/myuser/building-agent-loops",
  "url": "https://dev.to/myuser/building-agent-loops",
  "visibility": "PUBLIC"
}
```

## Authentication

Same OAuth2 flow as `linkedin_draft_post`. See [linkedin_draft_post](../linkedin-draft-post/README.md) for full setup instructions.

## Limitations

- LinkedIn generates the article preview card from the URL's Open Graph metadata — the `title` and `description` parameters set the share card fields but LinkedIn may override them with OG tags from the page
- No image upload — the preview image comes from the article's OG metadata
- Draft expires after 10 minutes if not published
