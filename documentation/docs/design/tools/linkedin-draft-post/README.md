# Tool: linkedin_draft_post

Create a draft LinkedIn text post for review before publishing.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `text` | string | Yes | Post text content (max 3000 characters) |
| `visibility` | string | No | `"PUBLIC"` (default) or `"CONNECTIONS"` |

## Behavior

- Validates the input and builds a LinkedIn API payload, but does **not** call the API
- Stores the payload in an in-memory draft store with a 10-minute TTL
- Returns a `draft_id` and human-readable preview
- The draft must be published via `linkedin_publish_draft` within 10 minutes
- **Availability:** Only registered when `LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET` are set. Job search tools remain available without credentials.

## Implementation

- Server: `mcp_servers/ts/packages/linkedin/src/tools/draft-post.ts`
- Draft store: `mcp_servers/ts/packages/linkedin/src/draft-store.ts`
- Auth: `mcp_servers/ts/packages/linkedin/src/auth/linkedin-auth.ts`

## Example

```
you> Post on LinkedIn: "Just shipped a new feature for our agent loop — LinkedIn publishing directly from the CLI. The draft-then-publish pattern means the agent always asks before posting."
```

Claude calls:
```json
{
  "name": "linkedin_draft_post",
  "input": {
    "text": "Just shipped a new feature for our agent loop — LinkedIn publishing directly from the CLI. The draft-then-publish pattern means the agent always asks before posting.",
    "visibility": "PUBLIC"
  }
}
```

Returns:
```json
{
  "draft_id": "a1b2c3d4-...",
  "preview": "[LinkedIn Text Post — PUBLIC]\n\nJust shipped a new feature...",
  "visibility": "PUBLIC",
  "char_count": 166
}
```

The agent then confirms with the user before calling `linkedin_publish_draft`.

## Authentication Setup (One-Time)

LinkedIn publishing requires OAuth 2.0 credentials. This is a one-time setup:

### 1. Create a LinkedIn Developer App

1. Go to https://www.linkedin.com/developers/apps
2. Click **Create app**
3. Fill in:
   - **App name**: e.g. "My Agent Publishing"
   - **LinkedIn Page**: Link to a LinkedIn Company Page (create a minimal personal one if needed)
   - **App logo**: Any image (required)
4. Accept the terms and create

### 2. Request API Products

Under the **Products** tab of your app:

1. **Sign In with LinkedIn using OpenID Connect** — click "Request access"
   - Grants scopes: `openid`, `profile`, `email`
   - Usually approved instantly
2. **Share on LinkedIn** — click "Request access"
   - Grants scope: `w_member_social`
   - Usually approved instantly for personal/testing use

### 3. Get Credentials

Under the **Auth** tab:

1. Note the **Client ID** and **Primary Client Secret**
2. Under **OAuth 2.0 settings**, add an authorized redirect URL:
   - `http://127.0.0.1` (the auth module uses a dynamic port, but LinkedIn requires at least this base)

### 4. Configure Environment

Add to your `.env` file:
```
LINKEDIN_CLIENT_ID=your-client-id
LINKEDIN_CLIENT_SECRET=your-client-secret
```

These are passed to the LinkedIn MCP server via the config's `env` block (already configured in `config-standard-no-summarization.json`).

### 5. First-Time Authorization

On the first call to any publishing tool:

1. A browser window opens to LinkedIn's authorization page
2. Sign in and approve the requested permissions
3. The browser redirects to a local server showing "Authorization successful!"
4. The access token and Person URN are saved to `.linkedin-tokens/token.json`

Subsequent calls reuse the cached token. Tokens expire after **60 days** — when expired, the browser flow re-runs automatically.

## Limitations

- Text posts only (no images or documents — use `linkedin_draft_article` for link shares)
- Maximum 3000 characters per post
- LinkedIn tokens expire after 60 days with no refresh token — requires re-authorization
- Draft expires after 10 minutes if not published
