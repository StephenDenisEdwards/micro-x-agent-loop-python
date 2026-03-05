# MCP Server Setup Guide

This guide covers how to set up each MCP server that ships with Micro-X. All servers live in `mcp_servers/ts/packages/` and run as stdio-based MCP servers managed by the agent.

## Quick Reference

| Server | Auth Type | Required Env Vars | Setup Effort |
|--------|-----------|-------------------|--------------|
| [filesystem](#filesystem) | None | — | None |
| [web](#web) | API key (optional) | `BRAVE_API_KEY` | Easy |
| [github](#github) | Personal Access Token | `GITHUB_TOKEN` | Easy |
| [google](#google) | OAuth 2.0 | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Medium |
| [linkedin](#linkedin) | OAuth 2.0 (publishing only) | `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET` | Medium |
| [anthropic-admin](#anthropic-admin) | API key | `ANTHROPIC_ADMIN_API_KEY` | Easy |
| [interview-assist](#interview-assist) | None | — | Hard (external dependencies) |

---

## filesystem

File read/write operations and user memory.

**Auth:** None

**Environment Variables:**

| Variable | Required | Description |
|----------|----------|-------------|
| `FILESYSTEM_WORKING_DIR` | No | Root directory the agent can access. Defaults to current working directory |
| `USER_MEMORY_DIR` | No | Directory for persistent user memory. If unset, the `save_memory` tool is not registered |
| `USER_MEMORY_MAX_LINES` | No | Max lines in memory file (default: 200) |

**Setup:** No credentials needed. Just configure paths in your agent config.

---

## web

Web fetching and search.

**Auth:** API key for search (fetch works without auth)

**Tools:**
- `web_fetch` — always available, no auth needed
- `web_search` — requires Brave Search API key

**Environment Variables:**

| Variable | Required | Description |
|----------|----------|-------------|
| `BRAVE_API_KEY` | For search only | Brave Search API key |

**Setup:**

1. Go to https://brave.com/search/api/
2. Sign up for the free tier (2,000 queries/month)
3. Copy your API key
4. Add to `.env`:
   ```
   BRAVE_API_KEY=your_key_here
   ```

If `BRAVE_API_KEY` is not set, the server starts without the search tool (fetch still works).

---

## github

GitHub repository operations: PRs, issues, file access, code search.

**Auth:** Personal Access Token

**Environment Variables:**

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_TOKEN` | Yes | GitHub Personal Access Token |

**Setup:**

1. Go to https://github.com/settings/tokens
2. Click **Generate new token (classic)** or use fine-grained tokens
3. Select scopes: `repo`, `read:org` (adjust based on what you need)
4. Copy the token
5. Add to `.env`:
   ```
   GITHUB_TOKEN=ghp_your_token_here
   ```

The server will not start without this variable.

---

## google

Gmail, Google Calendar, and Google Contacts.

**Auth:** OAuth 2.0 (browser-based consent flow)

**Environment Variables:**

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_CLIENT_ID` | Yes | OAuth 2.0 Client ID |
| `GOOGLE_CLIENT_SECRET` | Yes | OAuth 2.0 Client Secret |

**Setup:**

1. Go to https://console.cloud.google.com/
2. Create a project (or use an existing one)
3. Enable the APIs you need:
   - Gmail API
   - Google Calendar API
   - People API (for contacts)
4. Go to **APIs & Services > Credentials**
5. Click **Create Credentials > OAuth client ID**
6. Application type: **Desktop app**
7. Download the credentials or copy the Client ID and Client Secret
8. Go to **APIs & Services > OAuth consent screen**
   - Add your email as a test user (required while the app is in "Testing" status)
9. Add to `.env`:
   ```
   GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=your_client_secret
   ```

On first use, the server opens a browser for Google sign-in. The token is cached locally and refreshes automatically.

---

## linkedin

LinkedIn job search and content publishing.

The LinkedIn server has two distinct sets of tools with different requirements:

- **Job search tools** (`linkedin_jobs`, `linkedin_job_detail`) work immediately with no setup. They scrape public LinkedIn job listings and don't need API credentials.
- **Publishing tools** (`linkedin_draft_post`, `linkedin_draft_article`, `linkedin_publish_draft`) let the agent create posts on your LinkedIn profile. These require OAuth 2.0 credentials because they act on your behalf via LinkedIn's official API.

If you only need job search, skip the setup below entirely.

### Why OAuth 2.0?

Publishing to LinkedIn means the agent is posting as you. LinkedIn uses OAuth 2.0 to ensure you've explicitly granted permission for this — the agent can't post without you first logging in via your browser and approving access. This is a standard security model: the agent never sees your LinkedIn password, it only gets a time-limited access token.

**Environment Variables:**

| Variable | Required | Description |
|----------|----------|-------------|
| `LINKEDIN_CLIENT_ID` | For publishing | Identifies your registered app to LinkedIn |
| `LINKEDIN_CLIENT_SECRET` | For publishing | Proves your app's identity during token exchange (keep this secret) |

### Setup (publishing)

#### Step 1: Create a LinkedIn Developer App

Go to https://www.linkedin.com/developers/apps and click **Create app**.

LinkedIn requires every developer app to be associated with a **Company Page**. If you don't have one, create a personal Company Page first (Settings > Company Page > Create). The page doesn't need followers or content — it's just a LinkedIn requirement for app registration.

Fill in the app name (e.g. "Micro-X Agent"), select your Company Page, upload any logo, and accept the terms.

#### Step 2: Enable the required products

In your app's **Products** tab, you need to request access to two products. LinkedIn gates API permissions behind these product approvals — without them, the OAuth scopes the agent needs will be rejected.

| Product | What it grants | Why it's needed |
|---------|---------------|-----------------|
| **Sign In with LinkedIn using OpenID Connect** | `openid`, `profile`, `email` scopes | The agent needs to identify who you are to set the correct author on posts. This product allows the OAuth login flow and gives access to your basic profile info (name, LinkedIn ID). |
| **Share on LinkedIn** | `w_member_social` scope | This is the actual permission to create posts on your profile. Without it, the agent can authenticate but can't publish anything. |

"Sign In" approval is typically instant. "Share on LinkedIn" may take a few minutes. Both must show as approved before publishing will work.

#### Step 3: Get your credentials

Go to the **Auth** tab in your app. You'll see a **Client ID** and **Client Secret**. These are what the agent uses to identify itself to LinkedIn during the OAuth flow.

Add them to your `.env` file:

```
LINKEDIN_CLIENT_ID=your_client_id
LINKEDIN_CLIENT_SECRET=your_client_secret
```

#### Step 4: First-time authorization

No further manual setup is needed. On the first use of any publishing tool, the server automatically:

1. Starts a temporary local HTTP server on a random port
2. Opens your browser to LinkedIn's authorization page
3. You log in with your LinkedIn credentials and click "Allow"
4. LinkedIn redirects back to the local server with an authorization code
5. The server exchanges that code for an access token
6. The token is saved to `.linkedin-tokens/token.json`

You don't need to configure a redirect URL in the Developer Portal — the server handles this dynamically.

### Token lifetime

LinkedIn access tokens expire after **60 days**. Unlike Google, LinkedIn does not provide refresh tokens to most apps, so the token cannot be renewed silently. When it expires, the browser authorization flow runs again automatically the next time you use a publishing tool. You'll see a browser window open for re-authorization — just click "Allow" again.

### How publishing works

There is no tool that takes content and publishes it to LinkedIn in a single call. Instead, publishing is always a two-step process: **draft first, then publish**. This is a deliberate design choice, not a limitation.

> **Important: "draft" here means local-only, not a LinkedIn draft.** When you create a draft, nothing is sent to LinkedIn. The draft exists only in the MCP server's memory on your machine — it is not visible to anyone, not even as an unpublished draft on linkedin.com. LinkedIn's API does not support saving unpublished drafts; content is either not sent at all, or it's a live post. When you approve and the agent calls `linkedin_publish_draft`, the content goes **directly to a live, public post** on your LinkedIn feed. There is no intermediate "pending" or "draft" state on LinkedIn's side. The word "draft" refers to the local review step, not a LinkedIn concept.

#### Why two steps?

LinkedIn's API Terms of Use explicitly state "you must not use the APIs to automate posting." If the agent could draft and publish in one tool call, there would be nothing stopping it from posting without your knowledge — especially in long conversations where the LLM may lose track of earlier instructions. The two-step pattern makes it structurally impossible to bypass human review. The agent literally cannot publish without first creating a draft and obtaining a `draft_id`, which only happens when you've seen the preview.

We could have relied on the `ask_user` tool (which pauses the agent to ask you a question), but that's a behavioural safeguard — the LLM can choose to skip it. The draft-then-publish pattern is an architectural safeguard — there is no code path that bypasses it.

#### The flow

```
You:    "Write a LinkedIn post about our new release"
          │
          ▼
Agent:  calls linkedin_draft_post with the post text
          │
          ▼
Server: validates the input, formats a preview, generates a draft_id
        stores the draft in LOCAL MEMORY ONLY — nothing is sent to LinkedIn
          │
          ▼
Agent:  shows you the preview:
        ┌─────────────────────────────────────────┐
        │ "We just shipped v2.0 of Micro-X..."    │
        │                                         │
        │ Characters: 247 | Visibility: PUBLIC    │
        │ Draft ID: a1b2c3d4-...                  │
        └─────────────────────────────────────────┘
        "Shall I publish this?"
          │
          ▼
You:    review the preview — either approve, request changes, or abandon
          │
          ├── "Change the tone to be more casual"
          │     → agent creates a NEW draft, shows new preview
          │
          ├── "Never mind, don't post it"
          │     → draft expires after 10 minutes, nothing was posted
          │
          └── "Yes, publish it"
                │
                ▼
Agent:  calls linkedin_publish_draft with the draft_id
          │
          ▼
Server: looks up the draft, calls the LinkedIn API → POST GOES LIVE IMMEDIATELY
        returns the post URL — it is now visible on your LinkedIn feed
```

#### Draft lifecycle

Drafts are stored in the MCP server's memory (not on disk, not on LinkedIn). Key behaviours:

- **10-minute TTL** — drafts automatically expire. If you step away and come back after 10 minutes, the agent will need to create a new draft. This is intentional: it prevents stale content from being published accidentally.
- **One-time use** — once a draft is published, it's removed from the store. You can't publish the same draft twice.
- **Lost on restart** — if the MCP server restarts (e.g. the agent is restarted), all pending drafts are lost. Since drafts are just review artifacts with a short TTL, this is acceptable.
- **Revision creates a new draft** — if you ask the agent to change something, it creates a fresh draft with a new `draft_id`. The old draft is not modified.

#### What the agent sees vs. what LinkedIn sees

The draft tools are annotated with `readOnlyHint: true` — they tell the LLM "this tool doesn't change anything externally." Only `linkedin_publish_draft` is marked as non-read-only. This helps the LLM understand that drafting is safe to do freely, while publishing is a consequential action that needs explicit approval.

### Verify it works

Use these prompts in the agent to confirm each piece is working. Run them in order — each one tests a different layer of the setup.

**1. Check the tools are registered**

```
Show me what LinkedIn tools are available
```

You should see `linkedin_draft_post`, `linkedin_draft_article`, and `linkedin_publish_draft` in the list alongside the job search tools. If the publishing tools are missing, your `LINKEDIN_CLIENT_ID` is not set or not reaching the server — check your `.env` and config.

**2. Test the OAuth flow (first time only)**

```
Draft a LinkedIn post that says "Testing my agent integration — please ignore this post"
```

If this is your first time, a browser window should open asking you to authorize the app. After you click "Allow", the agent should return a draft preview with a `draft_id`. If the browser doesn't open, check stderr output for the authorization URL.

If you get an OAuth error mentioning invalid scopes, the required products ("Sign In with LinkedIn using OpenID Connect" and "Share on LinkedIn") are not yet approved in the Developer Portal.

**3. Test the draft preview**

The response from step 2 should show you a preview of the post including the text, character count, and visibility setting. Confirm the preview looks correct. You can ask the agent to revise it:

```
Change the visibility to connections only
```

This should create a new draft with `CONNECTIONS` visibility.

**4. Test publishing (optional — this will actually post)**

Only do this if you're happy to have a test post appear on your LinkedIn profile. You can delete it from LinkedIn afterwards.

```
Yes, publish it
```

The agent should call `linkedin_publish_draft` and return a URL to the published post. Click the URL to confirm it's live on your profile.

**5. Test article sharing**

```
Draft a LinkedIn article share for https://example.com with the title "Test Article" and description "Testing article shares from my agent"
```

This tests the article draft flow, which requires explicit title and description (LinkedIn doesn't auto-scrape URLs). You don't need to publish — just confirm the preview shows the article card layout correctly.

### Limitations

- **Write-only access** — the `w_member_social` scope can create posts but cannot read them back. To verify a post was published, check LinkedIn directly. Reading your own posts requires the `r_member_social` scope, which LinkedIn restricts to approved partners.
- **No image or document posts yet** — only text posts and article shares are currently implemented.
- **60-day token expiry** — requires periodic browser re-authorization (see above).

See also: [`mcp_servers/ts/packages/linkedin/README.md`](../../../mcp_servers/ts/packages/linkedin/README.md)

---

## anthropic-admin

Anthropic API administration (workspace and API key management).

**Auth:** Admin API key

**Environment Variables:**

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_ADMIN_API_KEY` | Yes | Anthropic Admin API key |

**Setup:**

1. Log in to the Anthropic Console
2. Go to API Keys and create an admin-level key
3. Add to `.env`:
   ```
   ANTHROPIC_ADMIN_API_KEY=your_admin_key
   ```

The server will not start without this variable.

---

## interview-assist

Interview analysis workflows with speech-to-text.

**Auth:** None (but has external dependencies)

**Environment Variables:** None required by the MCP server itself.

**External Dependencies:**
- .NET SDK (for the interview-assist-2 application)
- Deepgram API key (configured within the .NET app, not the MCP server)
- The `interview-assist-2` repo cloned and built locally

**Setup:** This server wraps an external .NET application. See the interview-assist-2 repo for its own setup instructions. The MCP server accepts `repo_path`, timeout, audio device, and STT parameters via tool inputs.

---

## General Notes

### Building the TypeScript servers

All servers must be built before first use:

```bash
cd mcp_servers/ts
npm install
npm run build
```

### Environment variables in config

Agent config files use `${VAR}` syntax to reference environment variables. Variables are typically loaded from a `.env` file in the project root. Example config entry:

```json
{
  "McpServers": {
    "github": {
      "command": "node",
      "args": ["mcp_servers/ts/packages/github/dist/index.js"],
      "transport": "stdio",
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}"
      }
    }
  }
}
```

### Conditional tool registration

Several servers conditionally register tools based on whether credentials are present:
- **web** — `web_search` only appears if `BRAVE_API_KEY` is set
- **linkedin** — publishing tools only appear if `LINKEDIN_CLIENT_ID` is set
- **filesystem** — `save_memory` only appears if `USER_MEMORY_DIR` is set

If a tool you expect is missing, check that the required environment variable is set.
