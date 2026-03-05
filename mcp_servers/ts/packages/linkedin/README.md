# LinkedIn MCP Server

MCP server for LinkedIn job search and content publishing.

## Tools

### Job Search (no auth required)

- **`linkedin_jobs`** — Search LinkedIn job listings
- **`linkedin_job_detail`** — Get full details for a specific job posting

### Publishing (requires OAuth setup)

- **`linkedin_draft_post`** — Create a local draft text post for review (nothing is sent to LinkedIn)
- **`linkedin_draft_article`** — Create a local draft article share for review (nothing is sent to LinkedIn)
- **`linkedin_publish_draft`** — Publish a previously drafted post (goes live immediately)

Publishing uses a **draft-then-publish** pattern: you always draft first, review the preview, then publish. There is no single-step publish tool — this is by design to comply with LinkedIn's API Terms of Use and ensure human review.

**Important:** "Draft" here means a local preview stored in the MCP server's memory — it is not visible to anyone and nothing is sent to LinkedIn. LinkedIn's API does not support saving unpublished drafts. When you publish, the post goes **directly live** on your feed. There is no intermediate "pending" state on LinkedIn's side.

## Setup

### Prerequisites

- Node.js 18+
- The monorepo TypeScript packages built (`npm run build` from `mcp_servers/ts/`)

### 1. Create a LinkedIn Developer App

1. Go to https://www.linkedin.com/developers/apps
2. Click **Create app**
3. You'll need a **LinkedIn Company Page** — if you don't have one, create a personal one first
4. Fill in the app name, page, and logo
5. Accept the terms and create the app

### 2. Enable Required Products

In your app's **Products** tab, request access to:

- **Sign In with LinkedIn using OpenID Connect** — grants `openid`, `profile`, `email` scopes
- **Share on LinkedIn** — grants `w_member_social` scope

Both must be approved before publishing tools will work. "Sign In" is typically instant; "Share on LinkedIn" may take a few minutes.

### 3. Set Environment Variables

Add to your `.env` file:

```
LINKEDIN_CLIENT_ID=your_client_id_here
LINKEDIN_CLIENT_SECRET=your_client_secret_here
```

Find these values under the **Auth** tab in your LinkedIn Developer App.

### 4. Agent Configuration

The LinkedIn server is configured in your agent config JSON. It should already be present if you're using a standard config:

```json
{
  "McpServers": {
    "linkedin": {
      "command": "node",
      "args": ["mcp_servers/ts/packages/linkedin/dist/index.js"],
      "transport": "stdio",
      "env": {
        "LINKEDIN_CLIENT_ID": "${LINKEDIN_CLIENT_ID}",
        "LINKEDIN_CLIENT_SECRET": "${LINKEDIN_CLIENT_SECRET}"
      }
    }
  }
}
```

If `LINKEDIN_CLIENT_ID` is not set, the server starts without publishing tools (job search still works).

### 5. First-Time Authentication

On the first use of any publishing tool, the server automatically:

1. Starts a local HTTP server on a random port
2. Opens your browser to LinkedIn's authorization page
3. You log in and grant permissions
4. The browser redirects back to the local server
5. The server exchanges the authorization code for an access token
6. The token is saved to `.linkedin-tokens/token.json`

No manual redirect URL configuration is needed — the server uses `http://127.0.0.1:{random_port}` dynamically.

**Note:** You do NOT need to add a redirect URL in the LinkedIn Developer Portal Auth tab. The server handles this automatically.

### Token Expiry

LinkedIn access tokens expire after **60 days**. Refresh tokens are not available for most apps. When the token expires, the browser authorization flow runs again automatically on the next publishing tool call.

## Usage

### Draft and publish a text post

```
you> Draft a LinkedIn post about our new MCP agent architecture
agent> [calls linkedin_draft_post with the text]
agent> Here's the draft preview:
       ---
       We just shipped a new MCP-based agent architecture that...
       ---
       Characters: 247 | Visibility: PUBLIC
       Shall I publish this?
you> Yes, go ahead
agent> [calls linkedin_publish_draft with the draft_id]
agent> Published! https://www.linkedin.com/feed/update/urn:li:share:123456789
```

### Draft and publish an article share

```
you> Share my blog post https://dev.to/mypost on LinkedIn
agent> [calls linkedin_draft_article with URL, title, description]
agent> Here's how the article card will look:
       ---
       Commentary: Check out my latest post on...
       Article: "Building Cost-Aware Agents" - dev.to/mypost
       ---
       Shall I publish?
you> Change the commentary to mention MCP specifically
agent> [calls linkedin_draft_article again with updated commentary]
agent> Updated draft:
       ---
       Commentary: How we used MCP to build a cost-aware agent...
       ---
       Publish this version?
you> Yes
agent> [calls linkedin_publish_draft]
```

## Limitations

- **Write-only** — the `w_member_social` scope cannot read back your posts. Use LinkedIn directly to check published content.
- **No image/document posts yet** — only text posts and article shares are implemented
- **Drafts are in-memory** — if the MCP server restarts, pending drafts are lost (10-minute TTL anyway)
- **60-day token expiry** — no programmatic refresh; browser re-auth required

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Publishing tools don't appear | Check that `LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET` are set in `.env` |
| "LinkedIn OAuth failed" | Ensure both products ("Sign In with LinkedIn using OpenID Connect" and "Share on LinkedIn") are approved in the Developer Portal |
| Browser doesn't open | Copy the URL printed to stderr and open it manually |
| "Draft not found or expired" | Drafts expire after 10 minutes — create a new one |
| HTTP 429 errors | LinkedIn rate limit hit — wait and retry (the server has automatic backoff) |
| HTTP 401 after weeks | Token expired (60-day lifetime) — the browser flow will re-run automatically |
