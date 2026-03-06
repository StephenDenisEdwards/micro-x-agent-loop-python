# MCP Server Setup Guide

This guide covers how to set up each MCP server used by Micro-X. Most servers live in `mcp_servers/ts/packages/` and run as stdio-based MCP servers managed by the agent. Some are external packages installed via npm.

## Quick Reference

| Server | Auth Type | Required Env Vars | Setup Effort |
|--------|-----------|-------------------|--------------|
| [filesystem](#filesystem) | None | — | None |
| [web](#web) | API key (optional) | `BRAVE_API_KEY` | Easy |
| [github](#github) | Personal Access Token | `GITHUB_TOKEN` | Easy |
| [google](#google) | OAuth 2.0 | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Medium |
| [linkedin](#linkedin) | OAuth 2.0 (publishing only) | `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET` | Medium |
| [x-twitter](#x-twitter) | OAuth 2.0 (PKCE) | `X_CLIENT_ID`, `X_CLIENT_SECRET` | Medium |
| [discord](#discord) | Bot Token | `DISCORD_TOKEN` | Easy |
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

GitHub repository operations: PRs, issues, discussions, file access, code search.

**Auth:** Personal Access Token

**Environment Variables:**

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_TOKEN` | Yes | GitHub Personal Access Token |

**Tools:**

| Tool | Description |
|------|-------------|
| `list_prs` | List pull requests |
| `get_pr` | Get PR detail (diff, reviews, CI status) |
| `create_pr` | Create a pull request |
| `list_issues` | List/search issues |
| `create_issue` | Create an issue |
| `get_file` | Get file contents from a repo |
| `search_code` | Search code across repos |
| `list_repos` | List repositories |
| `get_discussion_categories` | List discussion categories for a repo |
| `create_discussion` | Create a discussion |
| `list_discussions` | List/filter discussions |
| `get_discussion` | Get discussion with comments |
| `comment_on_discussion` | Comment or reply on a discussion |

**Setup:**

1. Go to https://github.com/settings/tokens
2. Create a token using one of the two options below
3. Copy the token
4. Add to `.env`:
   ```
   GITHUB_TOKEN=ghp_your_token_here
   ```

**Option A: Classic PAT** (simpler)

Click **Generate new token (classic)** and select these scopes:

| Scope | Covers |
|-------|--------|
| `repo` | PRs, issues, discussions, file access, code search |
| `read:org` | Organization membership (optional) |

**Option B: Fine-grained PAT** (more secure)

Click **Generate new token** (fine-grained), select your repository, then set these permissions:

| Permission | Level | Used by |
|------------|-------|---------|
| **Discussions** | Read and write | create/list/get/comment discussions |
| **Issues** | Read and write | create_issue, list_issues |
| **Pull requests** | Read and write | create_pr, list_prs, get_pr |
| **Contents** | Read | get_file, search_code |
| **Metadata** | Read | list_repos (granted automatically) |

**Note:** Discussions must be enabled on the target repository (Settings > Features > Discussions) for the discussion tools to work.

The server will not start without `GITHUB_TOKEN`.

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

## x-twitter

X (Twitter) tweet and thread publishing, analytics, and media upload.

The X server uses the same **draft-then-publish** pattern as the LinkedIn server. All posting goes through a two-step process: draft locally for review, then publish with explicit approval. See the [LinkedIn section](#how-publishing-works) for a detailed explanation of this pattern and why it exists.

**Auth:** OAuth 2.0 Authorization Code with PKCE

**Tools:**

| Tool | Description | Needs Auth |
|------|-------------|------------|
| `x_draft_tweet` | Create a draft tweet for review (local only) | Yes (for auth check) |
| `x_draft_thread` | Create a draft thread for review (local only) | Yes (for auth check) |
| `x_publish_draft` | Publish a previously drafted tweet or thread | Yes |
| `x_delete_tweet` | Delete a tweet by ID | Yes |
| `x_get_tweet` | Get tweet details and public metrics | Yes |
| `x_get_my_tweets` | Get your recent tweets with metrics | Yes |
| `x_upload_media` | Upload an image for use in tweets | Yes |

**Environment Variables:**

| Variable | Required | Description |
|----------|----------|-------------|
| `X_CLIENT_ID` | Yes | OAuth 2.0 Client ID from the X Developer Portal |
| `X_CLIENT_SECRET` | Yes | OAuth 2.0 Client Secret (keep this secret) |

### Setup

#### Step 1: Apply for X Developer Access

1. Go to https://developer.x.com
2. Sign in with your X (Twitter) account
3. You'll be asked to accept the developer agreement and describe your use case. Example description: *"Publishing technical content about open-source projects via an automated agent"*
4. Wait for approval — for the free tier, this is usually instant

#### Step 2: Create a Project and App

1. In the Developer Portal dashboard, click **Create Project**
2. Name it (e.g. "Micro-X Agent")
3. Select use case: **Making a bot** or **Building tools for myself**
4. Create an **App** within the project

#### Step 3: Configure OAuth 2.0

In your App's **Settings** tab, find **User authentication settings** and click **Set up**:

| Setting | Value |
|---------|-------|
| **App permissions** | Read and write |
| **Type of App** | Web App, Automated App or Bot (this makes it a confidential client) |
| **Callback URI** | `http://127.0.0.1:3000/callback` |
| **Website URL** | Any valid URL (e.g. your GitHub repo URL) |

Click **Save**. The "confidential client" type is important — it means your app has a client secret, which the server uses for secure token exchange via Basic auth.

> **Why `http://127.0.0.1:3000/callback`?** X requires at least one redirect URI registered in the portal. The MCP server actually uses a dynamic port (it picks a free port at runtime), but X validates the domain — `127.0.0.1` matches any localhost port. The callback URI in the portal is a security allowlist, not an exact match requirement for the port.

#### Step 4: Get your credentials

1. Go to the **Keys and tokens** tab in your App
2. Under **OAuth 2.0 Client ID and Client Secret**, copy both values
3. Add them to your `.env` file:
   ```
   X_CLIENT_ID=paste_client_id_here
   X_CLIENT_SECRET=paste_client_secret_here
   ```

Keep the Client Secret safe — it authenticates your app to X's token endpoint.

#### Step 5: First-time authorization

No further manual setup is needed. On the first use of any tool, the server automatically:

1. Generates a PKCE code verifier and SHA-256 challenge
2. Opens your browser to X's authorization page
3. You log in and click **Authorize app**
4. X redirects back to a local server with an authorization code
5. The server exchanges the code for access and refresh tokens (using Basic auth with your client credentials)
6. Fetches your user ID and @handle via `GET /2/users/me`
7. Tokens are saved to `.x-tokens/token.json`

You don't need to configure anything else — the server handles the full OAuth flow.

### Token lifetime

X access tokens expire after **2 hours**. Unlike LinkedIn's 60-day tokens, this is much shorter. However, X provides **refresh tokens** (when you request the `offline.access` scope, which this server does). The server automatically refreshes expired tokens without opening a browser. You should only need to re-authorize via the browser if the refresh token itself is revoked.

X uses **rotating refresh tokens** — each refresh returns a new refresh token. The server persists the latest refresh token to disk automatically.

### Free tier limitations

The X free tier is effectively **write-only**:

| Resource | Free Tier Limit |
|----------|----------------|
| Posts | 500/month |
| Reads | ~100/month |
| Media uploads (INIT) | 34/24 hours |

Read tools (`x_get_tweet`, `x_get_my_tweets`) will return a clear error message when the read quota is exhausted. Thread posting is expensive — each tweet in a thread counts as one post against the monthly quota.

The server handles rate limit responses (HTTP 429) and surfaces clear messages about quota exhaustion.

### Character counting

X uses weighted character counting. The server validates tweet length using the `twitter-text` npm package:

- Standard text: 1 character each
- Emojis: 2 characters each
- URLs (any length): always 23 characters (t.co wrapping)
- Max tweet length: 280 weighted characters

Draft tools validate character counts and return the weighted length in the preview.

### Verify it works

**1. Check tools are registered**

```
Show me what X/Twitter tools are available
```

If no tools appear, check that `X_CLIENT_ID` and `X_CLIENT_SECRET` are set in your `.env`.

**2. Test drafting**

```
Draft a tweet that says "Testing my agent integration"
```

On first use, a browser window opens for authorization. After approval, you should see a preview with the tweet text, character count, and a `draft_id`.

**3. Test publishing (optional — this will actually post)**

```
Yes, publish it
```

The agent calls `x_publish_draft` and returns the tweet URL.

### Limitations

- **Free tier is write-only in practice** — ~100 reads/month is negligible. Use read tools sparingly or upgrade to pay-per-use.
- **Thread posting burns quota fast** — a 10-tweet thread uses 10 of 500 free-tier monthly posts.
- **Quote tweets and media are mutually exclusive** — cannot combine in a single tweet.
- **No polls, DMs, or streaming** — out of scope for promotional publishing.

---

## discord

Discord server interaction: send/read messages, channel management, forums, reactions, and webhooks.

This is an **external package** ([mcp-discord](https://github.com/barryyip0625/mcp-discord)) installed via npm, not a custom server in `mcp_servers/ts/packages/`.

**Auth:** Discord Bot Token

**Environment Variables:**

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | Yes | Discord bot token |

**Installation:**

```bash
npm install -g mcp-discord
```

**Setup:**

#### Step 1: Create a Discord Application

1. Go to https://discord.com/developers/applications
2. Click **New Application** — name it (e.g. "Micro-X Agent")

#### Step 2: Create the Bot and get the token

1. Go to the **Bot** tab in the left sidebar
2. Click **Reset Token** → confirm → copy the token
3. Add to `.env`:
   ```
   DISCORD_TOKEN=your_bot_token_here
   ```

#### Step 3: Enable Privileged Gateway Intents

On the same **Bot** page, scroll down to **Privileged Gateway Intents** and enable:

| Intent | Required | Why |
|--------|----------|-----|
| **Message Content Intent** | Yes | Required to read message text (not just metadata) |
| **Server Members Intent** | No | Enables member lookups |
| **Presence Intent** | No | Enables online/offline status |

#### Step 4: Invite the bot to your server

1. Go to **OAuth2 → URL Generator**
2. Select scope: `bot`
3. Select bot permissions from the categories below:

**General Permissions:**

| Permission | Why |
|------------|-----|
| Manage Channels | Create/delete text channels and categories |
| Manage Webhooks | Create, edit, and delete webhooks |

**Text Permissions:**

| Permission | Why |
|------------|-----|
| Send Messages in Threads | Reply to forum posts (forums use threads internally) |
| Read Message History | `discord_read_messages` — read past messages in channels |
| Add Reactions | `discord_add_reaction` / `discord_add_multiple_reactions` |
| Embed Links | Allow bot messages to include link previews |

> **Note:** "Send Messages" and "Read Messages/View Channels" are included by default with the `bot` scope. If they appear as separate checkboxes, enable them too.

4. Copy the generated URL and open it in your browser
5. Select your Discord server and authorize

> **Re-inviting:** If the bot is already in your server but with wrong permissions, just generate a new URL with the correct permissions and open it. It will update the bot's permissions without creating a duplicate.

### Available tools

| Tool | Description |
|------|-------------|
| `discord_login` | Log in to Discord (auto-login if `DISCORD_TOKEN` is set) |
| `discord_send` | Send a message to a text channel |
| `discord_read_messages` | Read messages from a text channel (up to 100) |
| `discord_get_server_info` | Get server details including channels and member count |
| `discord_create_text_channel` | Create a new text channel |
| `discord_delete_channel` | Delete a channel |
| `discord_get_forum_channels` | List forum channels in a server |
| `discord_create_forum_post` | Create a post in a forum channel |
| `discord_get_forum_post` | Read a forum post and its replies |
| `discord_reply_to_forum` | Reply to a forum post |
| `discord_delete_forum_post` | Delete a forum post |
| `discord_add_reaction` | Add a reaction to a message |
| `discord_add_multiple_reactions` | Add multiple reactions at once |
| `discord_remove_reaction` | Remove a reaction |
| `discord_delete_message` | Delete a message |
| `discord_create_webhook` | Create a webhook for a channel |
| `discord_send_webhook_message` | Send a message via webhook |
| `discord_edit_webhook` | Edit a webhook |
| `discord_delete_webhook` | Delete a webhook |
| `discord_create_category` | Create a channel category |
| `discord_edit_category` | Edit a category |
| `discord_delete_category` | Delete a category |

### Server and channel IDs

All mcp-discord tools require **IDs**, not names. There is no "list all servers" tool — you must provide the guild (server) ID to get started.

**How to find your server ID:**

1. In Discord, go to **User Settings** (gear icon ⚙️, bottom left next to your username)
2. Navigate to **App Settings → Advanced**
3. Toggle **Developer Mode** to ON
4. Close settings
5. **Right-click the server icon** (the circle in the far left sidebar) → **Copy Server ID**

**How to find channel IDs:**

Once you have the server ID, call `discord_get_server_info` — it returns all channel IDs. After that, the agent can refer to channels by name within the conversation because it has the IDs in context.

**Tip — save your server ID to agent memory:**

On first use, tell the agent:

```
Remember my Discord server ID is <your-server-id>
```

This saves it to user memory so the agent knows it in future sessions without asking.

### Verify it works

Run these commands in order in the agent:

**1. Check the bot is connected and discover your server:**

```
Get server info for <your-server-id>
```

The agent should return your server's name, channels, and member count.

**2. Create a test channel:**

```
Create a text channel called "agent-test" on server <your-server-id>
```

**3. Send a test message:**

```
Send "Hello from Micro-X Agent!" to the agent-test channel
```

After the first `get_server_info` call, you can refer to channels by name — the agent has the IDs in context.

### Limitations

- **IDs required** — all tools need guild/channel/message IDs, not names. Use `discord_get_server_info` to discover IDs, and save your server ID to agent memory for convenience.
- **No "list servers" tool** — the bot cannot list which servers it's in. You must provide the server ID to get started.
- **No draft-then-publish pattern** — unlike LinkedIn and X/Twitter, messages are sent directly. The agent should use `ask_user` before sending messages to shared channels.
- **Bot permissions are server-specific** — the bot only has access to servers it's been invited to, with the permissions granted during invite.
- **Message Content Intent required** — without it, the bot can see message metadata but not the actual text content.

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
- **x-twitter** — all tools require `X_CLIENT_ID` and `X_CLIENT_SECRET` (no read-only fallback)
- **filesystem** — `save_memory` only appears if `USER_MEMORY_DIR` is set

If a tool you expect is missing, check that the required environment variable is set.
