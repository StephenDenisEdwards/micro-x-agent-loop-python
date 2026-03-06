# Plan: Reddit MCP Server

**Status: Blocked** (2026-03-06)

## Blocking Issue

Reddit's developer onboarding is broken. Creating a "script" app at `reddit.com/prefs/apps` requires reading the Responsible Builder Policy first, but that page provides no mechanism to acknowledge or proceed. The developer registration flow at `developers.reddit.com` redirects to **Devvit** (Reddit's subreddit app platform), which is an entirely different product — it creates Devvit projects, not OAuth API apps.

There is no working path from "new Reddit account" to "script app with client_id/client_secret" as of March 2026. The server code was fully built, compiled, and tested but had to be discarded because credentials cannot be obtained.

**Revisit when:** Reddit fixes their developer registration flow, or an alternative path to script app creation is discovered.

## Context

The agent needs to post technical content to targeted subreddits (r/mcp, r/ClaudeAI, r/LocalLLaMA) as part of the promotion workflow. It also needs to monitor post performance and reply to comments.

Reddit has a well-documented OAuth2 API with a free tier for personal/non-commercial use (100 QPM).

## Approach

Add a `reddit` MCP server (TypeScript) that uses the Reddit API with a "script" app type (personal use, password grant) to manage posts and comments.

### API

**Token endpoint:** `https://www.reddit.com/api/v1/access_token`
**API base URL:** `https://oauth.reddit.com` (NOT `www.reddit.com` — all authenticated calls go to `oauth.reddit.com`)

### Authentication: OAuth2 Password Grant (Script App)

Script apps are for personal use — only the developer's own account can authenticate.

**App registration:**
1. Go to `https://www.reddit.com/prefs/apps`
2. Click "create an app" → select **script**
3. Set redirect URI to `http://localhost:8080` (required but unused for password grant)
4. Note the `client_id` (14-char string under app name) and `client_secret`

**Token request:**
```
POST https://www.reddit.com/api/v1/access_token
Authorization: Basic base64(client_id:client_secret)
Content-Type: application/x-www-form-urlencoded
User-Agent: <platform>:<app_id>:<version> (by /u/<username>)

grant_type=password&username=<reddit_username>&password=<reddit_password>
```

**Token lifetime:** 3600 seconds (1 hour). Script apps cannot get refresh tokens — must re-authenticate with username+password. The MCP server should cache the token and auto-refresh before expiry.

**Required headers on every API request:**
```
Authorization: Bearer {access_token}
User-Agent: <platform>:<app_id>:<version> (by /u/<username>)
```

**Critical:** The `User-Agent` must be a custom string. Default library user-agents (e.g., `python-requests/2.x`) are severely rate-limited. Spoofing browsers or other bots results in an immediate ban.

### Reddit "Fullname" ID System

Reddit uses type-prefixed IDs throughout its API:

| Prefix | Type |
|--------|------|
| `t1_` | Comment |
| `t2_` | Account |
| `t3_` | Post/Submission |
| `t4_` | Private Message |
| `t5_` | Subreddit |

A fullname is `{prefix}_{base36_id}`, e.g., `t3_abc123` is a post. Many endpoints require the fullname, not the bare ID.

## Human-in-the-Loop: Draft-Then-Publish Pattern

All content-publishing tools use a **draft-then-publish** two-step pattern. See `PLAN-linkedin-publishing-mcp.md` for the full rationale. The same design applies here:

1. **Draft tool** — validates inputs, runs pre-flight checks (subreddit rules, flair requirements, domain restrictions), formats a preview. Returns a `draft_id` and preview. Does NOT call the Reddit API.
2. The LLM shows the preview to the user for review.
3. **Publish tool** — takes only a `draft_id`. Submits to Reddit.

Drafts are in-memory with a 10-minute TTL.

For Reddit specifically, the draft step also performs subreddit pre-flight validation (`GET /api/v1/{subreddit}/post_requirements`) so the user sees any rule violations before attempting to publish.

## Tool Definitions

### `reddit_draft_post`

Create a draft post for review. Does not submit to Reddit.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subreddit` | string | yes | Subreddit name (no `/r/` prefix) |
| `title` | string | yes | Post title |
| `kind` | string | yes | `self` (text) or `link` |
| `text` | string | conditional | Post body for text posts (Markdown supported). Required when `kind=self` |
| `url` | string | conditional | URL for link posts. Required when `kind=link` |
| `flair_id` | string | no | Flair template UUID (from `reddit_get_flairs`). Required if subreddit mandates flair |
| `flair_text` | string | no | Custom flair text (only if template allows editing) |
| `nsfw` | boolean | no | Mark as NSFW (default false) |
| `sendreplies` | boolean | no | Send inbox notifications for replies (default true) |

**Pre-flight validation (performed at draft time):** Calls `GET /api/v1/{subreddit}/post_requirements` to check:
- `is_flair_required` — error if flair required but not provided
- `body_restriction_policy` — error if body required but not provided, or body not allowed
- `domain_whitelist` / `domain_blacklist` — validate URL domain for link posts

Returns a preview (rendered title, body, subreddit, flair, any rule warnings) plus a `draft_id`.

**Markdown in `text`:** Reddit uses a custom CommonMark dialect. Key differences:
- Single newline is ignored (renders inline) — use double newlines for paragraphs
- HTML tags are stripped
- Supports: bold, italic, strikethrough, code blocks, tables, blockquotes, superscript, spoilers

**MCP annotations:** `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true`

### `reddit_publish_draft`

Publish a previously drafted post. This is the only tool that calls `POST /api/submit`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `draft_id` | string | yes | Draft ID returned by `reddit_draft_post` |

**Response parsing:** Success returns HTTP 200 with `json.data.name` (fullname) and `json.data.url`. Errors are in `json.errors` array — the HTTP status is 200 even on application errors like `RATELIMIT` or `NO_SELFS`.

**MCP annotations:** `readOnlyHint: false`, `destructiveHint: false`, `idempotentHint: false`

### `reddit_submit_comment`

Post a comment on a post or reply to another comment.

Comments do not use the draft pattern — they are lower-stakes and the LLM naturally includes the comment text in its response, giving the user visibility before the tool is called.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `parent_fullname` | string | yes | Fullname of parent — `t3_xxx` for top-level comment on a post, `t1_xxx` for reply to a comment |
| `text` | string | yes | Comment body (Markdown) |

**Endpoint:** `POST /api/comment` with `api_type=json`

**MCP annotations:** `readOnlyHint: false`, `destructiveHint: false`, `idempotentHint: false`

### `reddit_edit`

Edit an existing post body or comment.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `fullname` | string | yes | Fullname of post (`t3_xxx`) or comment (`t1_xxx`) to edit |
| `text` | string | yes | New body text (replaces existing entirely) |

**Endpoint:** `POST /api/editusertext` with `api_type=json`

Only works on the authenticated user's own posts/comments.

**MCP annotations:** `readOnlyHint: false`, `destructiveHint: false`, `idempotentHint: true`

### `reddit_delete`

Delete a post or comment.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `fullname` | string | yes | Fullname of the thing to delete |

**Endpoint:** `POST /api/del`

Permanent. Deleted post/comment body becomes `[deleted]`.

**MCP annotations:** `readOnlyHint: false`, `destructiveHint: true`, `idempotentHint: true`

### `reddit_get_post`

Get a post and its comments.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subreddit` | string | yes | Subreddit name |
| `post_id` | string | yes | Post ID (bare ID without `t3_` prefix) |
| `comment_sort` | string | no | `best` (default), `top`, `new`, `controversial`, `old` |
| `comment_limit` | number | no | Max comments to return (default 50, max 500) |

**Endpoint:** `GET /r/{subreddit}/comments/{post_id}`

Returns the post as the first listing element and comments as the second.

### `reddit_list_subreddit`

List posts from a subreddit.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subreddit` | string | yes | Subreddit name |
| `sort` | string | no | `hot` (default), `new`, `top`, `rising`, `controversial` |
| `time` | string | no | Time filter for `top`/`controversial`: `hour`, `day`, `week`, `month`, `year`, `all` |
| `limit` | number | no | Number of posts (default 25, max 100) |

**Endpoint:** `GET /r/{subreddit}/{sort}`

### `reddit_get_my_posts`

List the authenticated user's own submissions.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sort` | string | no | `new` (default), `hot`, `top`, `controversial` |
| `time` | string | no | Time filter for `top`/`controversial` |
| `limit` | number | no | Number of posts (default 25, max 100) |

**Endpoint:** `GET /user/{username}/submitted`

Useful for checking post performance (score, comments, upvote ratio).

### `reddit_get_flairs`

Get available post flair templates for a subreddit.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subreddit` | string | yes | Subreddit name |

**Endpoint:** `GET /r/{subreddit}/api/link_flair_v2`

Returns array of flair templates with `id` (UUID), `text`, `text_editable`, `type`, `background_color`, `text_color`. Use the `id` as `flair_id` in `reddit_submit_post`.

### `reddit_get_subreddit_rules`

Get subreddit rules and post requirements.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subreddit` | string | yes | Subreddit name |

Calls both:
- `GET /r/{subreddit}/about/rules` — human-readable rules
- `GET /api/v1/{subreddit}/post_requirements` — machine-readable restrictions (flair required, domain whitelist/blacklist, title length bounds, etc.)

Returns combined structured result so the agent can understand what's allowed before posting.

### `reddit_get_me`

Get the authenticated user's profile info.

**Endpoint:** `GET /api/v1/me`

Returns username, karma (link + comment), account age, verified status. Useful for the agent to understand the account's standing before posting.

## Output Schemas

### Post submission response
```json
{
  "success": true,
  "fullname": "t3_abc123",
  "post_id": "abc123",
  "url": "https://www.reddit.com/r/test/comments/abc123/my_post_title/"
}
```

### Post detail response
```json
{
  "fullname": "t3_abc123",
  "title": "...",
  "author": "username",
  "subreddit": "test",
  "score": 42,
  "upvote_ratio": 0.95,
  "num_comments": 12,
  "created_utc": 1709553600,
  "url": "...",
  "selftext": "...",
  "comments": [
    {
      "fullname": "t1_xyz789",
      "author": "commenter",
      "body": "...",
      "score": 5,
      "created_utc": 1709557200,
      "replies_count": 2
    }
  ]
}
```

## Configuration

```json
{
  "McpServers": {
    "reddit": {
      "command": "node",
      "args": ["mcp_servers/ts/packages/reddit/dist/index.js"],
      "transport": "stdio",
      "env": {
        "REDDIT_CLIENT_ID": "${REDDIT_CLIENT_ID}",
        "REDDIT_CLIENT_SECRET": "${REDDIT_CLIENT_SECRET}",
        "REDDIT_USERNAME": "${REDDIT_USERNAME}",
        "REDDIT_PASSWORD": "${REDDIT_PASSWORD}",
        "REDDIT_USER_AGENT": "windows:com.micro-x.reddit-mcp:v0.1.0 (by /u/${REDDIT_USERNAME})"
      }
    }
  }
}
```

**Note:** Reddit password is required for the script app password grant. This is the least-privilege approach for personal-use automation — no redirect server needed, no browser interaction. The password is stored in `.env` (gitignored).

## Rate Limits

### API request limits
- **100 queries per minute (QPM)** per OAuth client ID, enforced over a 10-minute rolling window (1000 requests per 10 minutes)
- Every response includes rate limit headers:
  - `X-Ratelimit-Used`: requests consumed in current window
  - `X-Ratelimit-Remaining`: requests remaining
  - `X-Ratelimit-Reset`: seconds until window resets
- HTTP 429 when exceeded

### Per-account posting limits (separate from API rate limits)
- Reddit throttles posting frequency per account based on: account age, karma, email verification, post removal rate
- When triggered, the submit response includes `json.errors: [["RATELIMIT", "you are doing that too much. try again in 9 minutes.", "ratelimit"]]` with `json.data.ratelimit` in seconds
- Many subreddits enforce "1 post per 24 hours" via AutoModerator

**Server design:**
- Monitor `X-Ratelimit-Remaining` proactively; back off before hitting 0
- Parse `data.ratelimit` from RATELIMIT errors and wait accordingly
- Exponential backoff on 429s

## Subreddit Access Restrictions

These are not fully machine-readable:
- **Account age / karma minimums** — enforced by AutoModerator, not exposed via API. Thresholds are deliberately hidden to prevent gaming. The agent will only learn of them via silent removal or AutoModerator reply.
- **Flair requirements** — machine-readable via `/api/v1/{subreddit}/post_requirements` `is_flair_required` field
- **Domain restrictions** — `domain_whitelist` / `domain_blacklist` in post requirements
- **Private/restricted subreddits** — check `subreddit_type` via `/r/{subreddit}/about` before posting

**Design approach:** Always call `reddit_get_subreddit_rules` before first post to a subreddit. The agent should review rules and validate the post content against them.

## Bot Policies

Key rules from Reddit API Terms and Responsible Builder Policy:
1. **No spam** — do not post identical content across multiple subreddits
2. **No vote manipulation** — never automate voting
3. **Disclose bot nature** — if the account is primarily bot-operated, the username should include "bot"
4. **Honest User-Agent** — never spoof browsers or other bots
5. **Subreddit-specific bot rules** — some subreddits ban bots entirely; check rules first
6. **Verified email** — accounts should have verified email for less restrictive posting limits

**For promotion use:** The account is the user's personal account posting original content with human review via the draft-then-publish pattern. This is within Reddit's acceptable use — it's not a bot spamming reposts.

## Key Gotchas

1. **Two different base domains** — token acquisition: `www.reddit.com`; all API usage: `oauth.reddit.com`
2. **Tokens expire in 1 hour** — script apps cannot get refresh tokens; must re-authenticate with username+password
3. **HTTP 200 on application errors** — always check `json.errors` array, not just HTTP status
4. **Parse `data.ratelimit`** from error responses to know backoff duration
5. **Double newlines for paragraphs** — single `\n` renders inline in Reddit Markdown
6. **Subreddit restrictions are partially invisible** — AutoModerator rules (karma/age requirements) are not exposed via API
7. **`api_type=json`** must be included in all POST requests for JSON responses
8. **Fullnames vs bare IDs** — some endpoints need `t3_abc123` (fullname), others need just `abc123` (bare ID). The `/api/del` and `/api/vote` endpoints use fullnames; `/r/{sub}/comments/{id}` uses bare IDs
9. **Maximum ~1000 posts retrievable** per listing regardless of pagination
10. **`resubmit` parameter** — by default, Reddit rejects URLs that have already been submitted. Set `resubmit=true` to allow re-posting a URL

## Not in Scope

- Image/video posts (require Reddit's media upload flow — add later if needed)
- Crossposting between subreddits
- Private messaging
- Subreddit moderation actions
- Award management
- Reddit chat
- Automated voting (violates Reddit ToS)
- Multi-account management

## Dependencies

- Reddit account with verified email
- Reddit "script" app registered at `https://www.reddit.com/prefs/apps`
- `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USERNAME`, `REDDIT_PASSWORD` in `.env`
- npm packages: `@modelcontextprotocol/sdk`, `zod`, `undici`
- Existing `@micro-x/mcp-shared` package

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Account banned for bot-like behavior | Lose posting ability | Draft-then-publish enforces human review; don't spam; vary content per subreddit |
| Silent post removal by AutoModerator | Posts don't appear, no error returned | Check post visibility after submitting (fetch and verify it appears in subreddit listing) |
| Password stored in `.env` | Security risk if `.env` leaks | `.env` is gitignored; consider 2FA implications (may need app-specific password) |
| 2FA on Reddit account | Password grant may fail with 2FA enabled | Reddit script apps work with 2FA by using the password directly (2FA is bypassed for API script apps per Reddit docs). Verify this during setup |
| Subreddit-specific karma/age gates | Cannot post to target subreddits | Build karma organically first; focus on subreddits where the account already qualifies |
| Per-account posting rate limits | Cannot post to multiple subreddits quickly | Space posts across sessions; don't batch-post |
