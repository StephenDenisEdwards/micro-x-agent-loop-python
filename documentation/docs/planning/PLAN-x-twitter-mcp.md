# Plan: X (Twitter) Publishing MCP Server

**Status: Completed** (2026-03-06)

## Context

The agent needs the ability to post technical content to X (Twitter) as part of the promotion workflow — short-form insights, thread-style breakdowns, and links to blog posts/repos.

X's API underwent significant changes in 2023-2026 (pricing tiers, v1.1 deprecation, pay-per-use launch). The free tier is effectively write-only (500 posts/month, ~100 reads/month), which is sufficient for a promotional publishing use case but not for analytics or engagement monitoring.

## Tier Assessment

| Tier | Monthly Cost | Posts/Month | Reads/Month | Verdict |
|------|-------------|-------------|-------------|---------|
| **Free** | $0 | 500 | ~100 | Sufficient for publishing. Cannot read timelines or search. |
| **Pay-per-use** | Variable | $0.01/post | $0.005/read | Better for occasional use + light analytics |
| **Basic** | $200/mo | 50,000 | 15,000 | Overkill for personal promotion |
| **Pro** | $5,000/mo | 300,000 | 1,000,000 | Not needed |

**Recommendation:** Start with **Free** tier for write-only publishing. Upgrade to pay-per-use if analytics/engagement monitoring becomes important. The MCP server should support both — analytics tools gracefully degrade (return "upgrade required" errors) on the free tier.

## Approach

Add an `x-twitter` MCP server (TypeScript) that uses the X API v2 with OAuth 2.0 PKCE for user-context operations.

### API: X API v2

**Base URL:** `https://api.x.com/2/`

### Authentication: OAuth 2.0 Authorization Code with PKCE

Required for all write operations (posting, deleting).

**Flow:**
1. Generate PKCE `code_verifier` (43-128 chars, URL-safe base64) and `code_challenge` (`BASE64URL(SHA256(code_verifier))`)
2. Redirect user to `https://x.com/i/oauth2/authorize` with scopes, client_id, redirect_uri, code_challenge
3. User authorizes → redirected to callback with `?code=...`
4. Exchange code for tokens: `POST https://api.x.com/2/oauth2/token`
5. Store access token (expires 2 hours) and refresh token

**Required scopes:** `tweet.read tweet.write users.read offline.access media.write`

**Token refresh:** `POST https://api.x.com/2/oauth2/token` with `grant_type=refresh_token`. The `offline.access` scope is critical — without it, there are no refresh tokens and the user must re-authorize every 2 hours.

**Token storage:** Persist access token, refresh token, and expiry to `.x-tokens/token.json`. Auto-refresh on expiry using the refresh token.

### Developer Portal Setup

1. Go to `https://developer.x.com`
2. Apply for developer access (describe promotional publishing use case)
3. Create a Project → Create an App within it
4. Enable OAuth 2.0 in app settings, set type to "confidential" (server-side)
5. Set callback/redirect URI (e.g., `http://localhost:3000/callback`)
6. Generate and store: Client ID, Client Secret

## Human-in-the-Loop: Draft-Then-Publish Pattern

All content-publishing tools use a **draft-then-publish** two-step pattern. See `PLAN-linkedin-publishing-mcp.md` for the full rationale. The same design applies here:

1. **Draft tool** — validates inputs (character count, media existence), formats a preview showing exactly what will be posted. Returns a `draft_id` and preview. Does NOT call the X API.
2. The LLM shows the preview to the user for review.
3. **Publish tool** — takes only a `draft_id`. Posts the tweet(s).

Drafts are in-memory with a 10-minute TTL.

For threads, the draft step validates all tweets in the thread (character counts, media) and shows the complete thread preview. The publish step posts all tweets sequentially.

## Tool Definitions

### `x_draft_tweet`

Create a draft tweet for review. Does not post.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `text` | string | yes | Tweet text (max 280 chars; 25,000 for X Premium subscribers) |
| `reply_to_id` | string | no | Tweet ID to reply to (for replies) |
| `quote_tweet_id` | string | no | Tweet ID to quote |
| `media_paths` | string[] | no | Local paths to images (max 4). Validated at draft time, uploaded at publish time |

**Character counting:** URLs always count as 23 characters regardless of length. Emojis count as 2 characters. The server validates length at draft time using weighted character counting rules (via the `twitter-text` npm package) and returns the weighted count in the preview.

**Mutually exclusive:** `media`, `quote_tweet_id`, and `poll` cannot be combined in a single tweet. Validated at draft time.

Returns a preview (rendered text, character count, media summary, quote context) plus a `draft_id`.

**MCP annotations:** `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true`

### `x_draft_thread`

Create a draft thread (multiple tweets) for review. Does not post.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `tweets` | object[] | yes | Array of `{ text: string, media_paths?: string[] }` objects, in order |

Validates all tweets (character counts, media). Returns a preview showing the complete thread with numbered tweets, character counts, and a quota impact note (e.g., "This thread will use 5 of your 500 free-tier monthly posts").

**Important:** Each tweet in a thread counts against the monthly post quota independently. A 10-tweet thread uses 10 of the 500 free-tier monthly posts.

Returns a `draft_id` for the entire thread.

**MCP annotations:** `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true`

### `x_publish_draft`

Publish a previously drafted tweet or thread. This is the only tool that calls the X API to create content.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `draft_id` | string | yes | Draft ID returned by `x_draft_tweet` or `x_draft_thread` |

For single tweets: posts the tweet (including media upload if applicable).
For threads: posts each tweet sequentially, using the previous tweet's ID as `reply.in_reply_to_tweet_id`.

**Error handling (threads):** If any tweet in the thread fails, the server returns the partial result (successfully posted tweets) plus the error. It does NOT attempt to delete already-posted tweets — that would consume additional quota and rate limit budget.

**MCP annotations:** `readOnlyHint: false`, `destructiveHint: false`, `idempotentHint: false`

### `x_delete_tweet`

Delete a tweet.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `tweet_id` | string | yes | ID of the tweet to delete |

**Endpoint:** `DELETE https://api.x.com/2/tweets/{id}`

**Rate limit:** 50 requests per 15 minutes per user.

**MCP annotations:** `readOnlyHint: false`, `destructiveHint: true`, `idempotentHint: true`

### `x_get_tweet`

Get a tweet's details and public metrics.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `tweet_id` | string | yes | Tweet ID |

**Endpoint:** `GET https://api.x.com/2/tweets/{id}?tweet.fields=created_at,public_metrics,author_id,conversation_id,entities&expansions=author_id`

**Note:** On the free tier, reads are severely limited (~100/month). This tool may return a quota error. The server should surface a clear message: "X API read quota exhausted. Upgrade to Basic or pay-per-use for read access."

### `x_get_my_tweets`

Get the authenticated user's recent tweets with metrics.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `max_results` | number | no | Number of tweets (default 10, max 100) |

**Endpoint:** `GET https://api.x.com/2/users/{user_id}/tweets?tweet.fields=created_at,public_metrics,conversation_id&max_results={n}`

**Prerequisite:** Fetch user ID via `GET /2/users/me` on first call, then cache it.

**Same free-tier read limitation applies.** This tool is most useful on Basic or pay-per-use.

### `x_upload_media`

Upload an image for use in a tweet. Returns a `media_id` to pass to `x_post_tweet`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `file_path` | string | yes | Local path to image (JPG, PNG, GIF) |
| `alt_text` | string | no | Alt text for accessibility |

**Process (chunked upload, v2):**
1. `POST /2/media/upload` with `command=INIT`, `total_bytes`, `media_type`, `media_category=tweet_image`
2. `POST /2/media/upload` with `command=APPEND`, `media_id`, `segment_index=0`, binary chunk
3. `POST /2/media/upload` with `command=FINALIZE`, `media_id`
4. If `alt_text` provided: `POST /2/media/upload` with `command=METADATA`, add alt text

**Free tier limits:** 34 INIT requests per 24 hours, 85 APPEND requests per 24 hours per user. This effectively limits uploads to ~34 images per day.

**Media IDs expire after ~24 hours.** Upload and attach to a tweet in the same session.

**Note:** `x_post_tweet` with `media_paths` calls this internally. This tool is exposed separately for cases where the agent wants to pre-upload media.

## Output Schemas

### Tweet post response
```json
{
  "success": true,
  "tweet_id": "1234567890123456789",
  "text": "Hello world",
  "url": "https://x.com/username/status/1234567890123456789"
}
```

### Thread post response
```json
{
  "success": true,
  "thread_url": "https://x.com/username/status/1234567890123456789",
  "tweets": [
    { "tweet_id": "1234567890123456789", "text": "First tweet..." },
    { "tweet_id": "1234567890123456790", "text": "Second tweet..." }
  ],
  "posts_used": 2,
  "monthly_quota_note": "2 of 500 free-tier posts used this month"
}
```

### Tweet detail response
```json
{
  "tweet_id": "1234567890123456789",
  "text": "...",
  "created_at": "2026-03-04T10:00:00Z",
  "public_metrics": {
    "retweet_count": 5,
    "reply_count": 3,
    "like_count": 42,
    "quote_count": 1,
    "impression_count": 1234
  },
  "conversation_id": "1234567890123456789",
  "url": "https://x.com/username/status/1234567890123456789"
}
```

## Configuration

```json
{
  "McpServers": {
    "x-twitter": {
      "command": "node",
      "args": ["mcp_servers/ts/packages/x-twitter/dist/index.js"],
      "transport": "stdio",
      "env": {
        "X_CLIENT_ID": "${X_CLIENT_ID}",
        "X_CLIENT_SECRET": "${X_CLIENT_SECRET}",
        "X_TOKEN_PATH": ".x-tokens/token.json",
        "X_CALLBACK_PORT": "3000"
      }
    }
  }
}
```

## Rate Limits

### Per-endpoint limits (15-minute windows unless noted)

| Endpoint | Per App | Per User |
|----------|---------|----------|
| `POST /2/tweets` | 10,000/24hrs | 100/15min |
| `DELETE /2/tweets/:id` | — | 50/15min |
| `GET /2/tweets/:id` | 450/15min | 900/15min |
| `GET /2/users/:id/tweets` | 10,000/15min | 900/15min |
| `POST /2/media/upload` (INIT) | — | 34/24hrs (free) |
| `POST /2/media/upload` (APPEND) | — | 85/24hrs (free) |

### Monthly quota (billing-level caps)

| Tier | Posts | Reads |
|------|-------|-------|
| Free | 500 | ~100 |
| Pay-per-use | $0.01/post | $0.005/read |
| Basic ($200/mo) | 50,000 | 15,000 |

**Rate limit headers:** `x-rate-limit-limit`, `x-rate-limit-remaining`, `x-rate-limit-reset` (Unix epoch seconds).

**Server design:** Track monthly post count locally (persist to disk). Warn when approaching 500-post free-tier limit. Implement 429 handling with `Retry-After` header parsing and exponential backoff.

## Character Counting

X uses weighted character counting (implemented in `twitter-text` npm package):

| Content | Weight |
|---------|--------|
| Standard ASCII | 1 each |
| Most Unicode (including CJK) | 1 each |
| Emojis | 2 each |
| URLs (any length) | Always 23 |
| @mentions at start of reply | 0 (not counted) |

**Server validation:** Before posting, validate text length using `twitter-text` library. Return a clear error if over limit, including the weighted character count.

## Key Gotchas

1. **Free tier is write-only in practice.** ~100 reads/month is negligible. Read tools should gracefully degrade with a clear upgrade message.
2. **v1.1 media upload was deprecated March 31, 2025.** All media uploads must use the v2 chunked upload pattern (INIT → APPEND → FINALIZE).
3. **Thread posting is N sequential API calls.** Each tweet counts against monthly quota independently. No batch endpoint.
4. **Access tokens expire in 2 hours.** Always request `offline.access` scope for refresh tokens. Without it, user must re-authorize constantly.
5. **Media IDs expire after ~24 hours.** Upload and post in the same session.
6. **URLs always count as 23 characters** regardless of actual length (t.co wrapping).
7. **Rate limits and monthly quotas are independent.** Both return HTTP 429 but with different recovery strategies (wait 15 min vs. wait until next month).
8. **Pay-per-use (Feb 2026) is now the default for new developers.** The free tier still exists but may be phased out. Consider pay-per-use for flexibility.
9. **`POST /2/tweets` returns HTTP 201 on success** (not 200). Check for 201 specifically.
10. **Quote tweets and media are mutually exclusive** in a single tweet. Cannot quote-tweet with an attached image.

## Not in Scope

- Polls (low priority for promotion; also mutually exclusive with media)
- Direct messages
- Following/unfollowing
- Liking/retweeting (could be added for engagement but low priority)
- Streaming/filtered stream (requires Pro tier)
- Full-archive search (requires Pro tier, $5,000/mo)
- Spaces (live audio)
- Lists management
- Bookmarks

## Dependencies

- X (Twitter) developer account at `https://developer.x.com`
- App created with OAuth 2.0 enabled (confidential client type)
- `X_CLIENT_ID` and `X_CLIENT_SECRET` in `.env`
- npm packages: `@modelcontextprotocol/sdk`, `zod`, `undici`, `twitter-text` (for character counting)
- Existing `@micro-x-ai/mcp-shared` package

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Free tier eliminated | Must pay for API access | Pay-per-use is affordable for light use ($0.01/post = $5 for 500 posts) |
| 500 posts/month limit on free tier | Thread-heavy strategy burns quota fast | Monitor quota locally; warn when approaching limit; keep threads concise |
| 2-hour token expiry | Frequent re-auth interruptions | Use `offline.access` scope for refresh tokens; auto-refresh before expiry |
| Free tier cannot read tweets | Cannot verify posts appeared or check metrics | Accept limitation; check manually on X; upgrade to pay-per-use if needed |
| API pricing changes | X has changed pricing multiple times since 2023 | Design server to be tier-agnostic; graceful degradation on quota errors |
| Account suspension for bot-like behavior | Lose posting ability | Draft-then-publish enforces human review; don't auto-post; vary content |
| Media upload limits on free tier (34 INIT/day) | Cannot post many image-heavy threads | Prioritize text-only posts; reserve media uploads for high-impact content |
