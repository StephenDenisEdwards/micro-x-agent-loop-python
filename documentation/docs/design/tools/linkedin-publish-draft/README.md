# Tool: linkedin_publish_draft

Publish a previously created LinkedIn draft to your profile.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `draft_id` | string (UUID) | Yes | Draft ID returned by `linkedin_draft_post` or `linkedin_draft_article` |

## Behavior

- Looks up the draft from the in-memory store
- If the draft is not found or has expired (10-minute TTL), returns an error
- Calls `POST https://api.linkedin.com/rest/posts` with the stored payload
- Extracts the post URN from the `x-restli-id` response header
- Returns the post URN and a link to the published post
- Removes the draft from the store after successful publication
- **Availability:** Only registered when `LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET` are set

## Implementation

- Server: `mcp_servers/ts/packages/linkedin/src/tools/publish-draft.ts`
- Draft store: `mcp_servers/ts/packages/linkedin/src/draft-store.ts`
- Auth: `mcp_servers/ts/packages/linkedin/src/auth/linkedin-auth.ts`
- Uses `resilientFetch` with `LinkedIn-Version: 202601` and `X-Restli-Protocol-Version: 2.0.0` headers

## Example

After creating a draft:

```
you> Yes, publish it
```

Claude calls:
```json
{
  "name": "linkedin_publish_draft",
  "input": {
    "draft_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  }
}
```

Returns:
```json
{
  "post_urn": "urn:li:share:7123456789012345678",
  "post_url": "https://www.linkedin.com/feed/update/urn:li:share:7123456789012345678/"
}
```

## Error Cases

| Scenario | Error Message |
|----------|---------------|
| Draft not found | "Draft not found or expired. Drafts expire after 10 minutes. Please create a new draft." |
| Draft expired (>10 min) | Same as above — expired drafts are automatically removed |
| LinkedIn API error | "LinkedIn API error (HTTP status): error details" |
| Token expired | Browser re-authorization flow triggers automatically |

## Authentication

Same OAuth2 flow as `linkedin_draft_post`. See [linkedin_draft_post](../linkedin-draft-post/README.md) for full setup instructions.

## Limitations

- Can only publish drafts created in the current server session (drafts are in-memory, not persisted)
- If the MCP server restarts, all pending drafts are lost
- LinkedIn may take a few seconds to make the post visible in the feed after the API returns success
