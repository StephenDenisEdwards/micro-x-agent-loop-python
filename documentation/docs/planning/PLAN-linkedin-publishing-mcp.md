# Plan: LinkedIn Publishing MCP Server

**Status: Completed**

## Context

The agent currently has LinkedIn job search tools (scraping-based) but no ability to publish content. For promotional workflow support, the agent needs to create posts, share articles, and upload media to LinkedIn on the user's behalf.

LinkedIn is the highest-priority publishing channel for this project's target audience (senior engineers, CTOs, hiring managers).

## Approach

Add a `linkedin-publishing` MCP server (TypeScript) that uses the LinkedIn Posts API (v2 REST gateway) to create and manage content on the authenticated user's personal profile.

### API: LinkedIn Posts API (REST)

The current Posts API (`/rest/posts`) replaces the legacy UGC Posts API (`/v2/ugcPosts`). All new development should target the REST gateway.

**Base URL:** `https://api.linkedin.com/rest/`

**Required headers on every request:**
```
Authorization: Bearer {access_token}
Linkedin-Version: 202601
X-Restli-Protocol-Version: 2.0.0
Content-Type: application/json
```

The `Linkedin-Version` header is mandatory and must be a supported version (YYYYMM format). LinkedIn sunsets each version ~12 months after release on a rolling monthly basis.

### Authentication: OAuth 2.0 (3-Legged Flow)

| Step | Endpoint |
|------|----------|
| Authorization | `GET https://www.linkedin.com/oauth/v2/authorization` |
| Token Exchange | `POST https://www.linkedin.com/oauth/v2/accessToken` |
| User Info | `GET https://api.linkedin.com/v2/userinfo` |

**Required scopes:**
- `openid` + `profile` + `email` — via "Sign In with LinkedIn using OpenID Connect" product
- `w_member_social` — via "Share on LinkedIn" product

**Scope prerequisite:** Both products must be enabled in the LinkedIn Developer Portal (under the Products tab). Scopes are gated by product approval.

**Token lifetime:** 5,184,000 seconds (60 days). Refresh tokens are only available to approved partners — for most apps, the user must re-authenticate after expiry.

**Author URN:** After authentication, call `/v2/userinfo` to get the `sub` field. The Person URN is `urn:li:person:{sub}`.

**Token storage:** Persist the access token and expiry timestamp to a local file (e.g., `.linkedin-tokens/token.json`), similar to the existing Google OAuth pattern. On startup, check if the token is still valid; if expired, prompt re-authentication.

### Developer Portal Setup

1. Go to https://www.linkedin.com/developers/apps
2. Create a new app (requires a LinkedIn Company Page — can be a personal one)
3. Under Products tab, request access to:
   - "Sign In with LinkedIn using OpenID Connect"
   - "Share on LinkedIn"
4. Under Auth tab, add redirect URL: `http://localhost:3000/callback`
5. Note the Client ID and Client Secret

**Important deprecation:** The old scopes `r_liteprofile` and `r_emailaddress` are deprecated. Use the OIDC scopes (`openid`, `profile`, `email`) instead.

## Human-in-the-Loop: Draft-Then-Publish Pattern

LinkedIn's API Terms of Use state "you must not use the APIs to automate posting." To comply, all publishing tools use a **draft-then-publish** two-step pattern that is enforced architecturally — the LLM cannot skip the review step.

### How it works

1. **Draft tool** — validates inputs, formats the post preview (rendered text, character count, visibility, media summary). Returns a `draft_id` and preview. Does NOT call the LinkedIn API.
2. The LLM naturally shows the preview to the user. The user reviews and says "looks good" or "change X."
3. **Publish tool** — takes only a `draft_id`. Looks up the draft from the in-memory store, calls the LinkedIn API, and publishes.

### Server-side implementation

Drafts live in-memory in the MCP server process as a `Map<string, DraftPost>` with a 10-minute TTL. No persistence needed — drafts are ephemeral review artifacts.

```typescript
interface DraftPost {
  id: string;                    // UUID
  type: "text" | "article" | "image" | "document";
  payload: LinkedInPostPayload;  // Validated, ready to send
  preview: string;               // Human-readable preview
  createdAt: number;             // For TTL expiry
}
```

The `linkedin_publish_draft` tool rejects expired or unknown draft IDs with a clear error: "Draft expired or not found. Please create a new draft."

### Why not just use `ask_user`?

The `ask_user` pseudo-tool (ADR-017) relies on the LLM voluntarily calling it before publishing. This is behavioral, not enforced — the LLM can skip it, especially in long conversations where system prompt instructions get compacted. The draft-then-publish pattern is structurally enforced: there is no tool that accepts content and publishes it in a single call.

## Tool Definitions

### `linkedin_draft_post`

Create a draft text post for review. Does not publish.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `text` | string | yes | Post body. Supports `#hashtags` and `@[Name](urn:li:organization:ID)` mentions |
| `visibility` | string | no | `PUBLIC` (default), `CONNECTIONS`, or `LOGGED_IN` |

Returns a preview of the post as it will appear, plus a `draft_id` for use with `linkedin_publish_draft`.

**MCP annotations:** `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true`

### `linkedin_draft_article`

Create a draft article share for review. Does not publish.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | yes | Article URL to share |
| `title` | string | yes | Article title (LinkedIn does NOT auto-scrape OG tags) |
| `description` | string | yes | Article description |
| `commentary` | string | no | Post text above the article card |
| `thumbnail_path` | string | no | Local path to thumbnail image (will be uploaded at publish time) |
| `visibility` | string | no | `PUBLIC` (default), `CONNECTIONS`, or `LOGGED_IN` |

**Important:** The Posts API does not perform URL scraping. All article metadata (title, description, thumbnail) must be supplied explicitly.

Returns a preview including the article card layout, plus a `draft_id`.

**MCP annotations:** `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true`

### `linkedin_draft_image_post`

Create a draft image post for review. Does not publish or upload.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `text` | string | yes | Post body |
| `image_path` | string | yes | Local path to image file (JPG, PNG, GIF) |
| `alt_text` | string | no | Image alt text for accessibility |
| `visibility` | string | no | `PUBLIC` (default), `CONNECTIONS`, or `LOGGED_IN` |

Validates the image exists and is a supported format. Returns a preview (text + image filename/size), plus a `draft_id`. The actual image upload (3-step: initializeUpload → PUT bytes → reference URN) happens at publish time.

Supported formats: JPG, PNG, GIF (up to 250 frames). Max: 36,152,320 pixels.

**MCP annotations:** `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true`

### `linkedin_draft_document_post`

Create a draft document post for review. Does not publish or upload.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `text` | string | yes | Post body |
| `document_path` | string | yes | Local path to document (PDF, PPTX, DOCX) |
| `document_title` | string | no | Display title for the document |
| `visibility` | string | no | `PUBLIC` (default), `CONNECTIONS`, or `LOGGED_IN` |

Validates the document exists and is a supported format. Upload via `/rest/documents?action=initializeUpload` happens at publish time. Max: 100MB, 300 pages.

**MCP annotations:** `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true`

### `linkedin_publish_draft`

Publish a previously drafted post. This is the only tool that calls the LinkedIn API to create content.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `draft_id` | string | yes | Draft ID returned by any `linkedin_draft_*` tool |

Looks up the draft from the in-memory store. If found and not expired (10-minute TTL), executes the LinkedIn API call (including media upload if applicable). Returns the published post URL and URN.

Rejects expired or unknown draft IDs with: "Draft expired or not found. Please create a new draft."

**MCP annotations:** `readOnlyHint: false`, `destructiveHint: false`, `idempotentHint: false`

### `linkedin_get_my_posts`

List the authenticated user's recent posts.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `count` | number | no | Number of posts to return (default 10) |

**Endpoint:** `GET /rest/posts?q=author&author={encoded_urn}&count={count}`

**Note:** Requires `r_member_social` scope, which is restricted to approved partners. If unavailable, this tool returns an error with instructions. The write-only tools (`w_member_social`) work without this scope.

### `linkedin_delete_post`

Delete a post by URN.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `post_urn` | string | yes | Full URN (e.g., `urn:li:share:123456` or `urn:li:ugcPost:123456`) |

**Endpoint:** `DELETE /rest/posts/{url_encoded_urn}`

**MCP annotations:** `readOnlyHint: false`, `destructiveHint: true`, `idempotentHint: true`

## Output Schemas

All tools return structured JSON via `structuredContent`.

### Post creation response
```json
{
  "success": true,
  "post_urn": "urn:li:share:7048823456789012345",
  "post_url": "https://www.linkedin.com/feed/update/urn:li:share:7048823456789012345"
}
```

**Gotcha:** The created post URN is returned in the `x-restli-id` response **header**, not the response body. The server must extract it from there.

## Configuration

```json
{
  "McpServers": {
    "linkedin-publishing": {
      "command": "node",
      "args": ["mcp_servers/ts/packages/linkedin-publishing/dist/index.js"],
      "transport": "stdio",
      "env": {
        "LINKEDIN_CLIENT_ID": "${LINKEDIN_CLIENT_ID}",
        "LINKEDIN_CLIENT_SECRET": "${LINKEDIN_CLIENT_SECRET}",
        "LINKEDIN_TOKEN_PATH": ".linkedin-tokens/token.json",
        "LINKEDIN_API_VERSION": "202601"
      }
    }
  }
}
```

## Rate Limits

LinkedIn does not publish specific numeric rate limits. Key facts:
- Limits reset daily at midnight UTC
- Two types: application-level (total calls/day) and member-level (calls/day/member)
- Rate-limited requests receive HTTP 429
- Developer portal Analytics tab shows actual limits (only for endpoints already called)
- Third-party estimates: ~100 requests/day/user for basic access (unconfirmed)

**Server design:** Implement exponential backoff on 429s. Log rate limit state for visibility.

## Key Gotchas

1. **Post URN is in the `x-restli-id` response header**, not the body
2. **No URL scraping for articles** — must supply title, description, thumbnail explicitly
3. **Two-step media upload** for images, videos, documents (initialize → PUT bytes → reference URN)
4. **`w_member_social` is write-only** — cannot GET images or read posts back without `r_member_social` (restricted scope)
5. **URL-encode URNs in paths** — `urn:li:person:abc` → `urn%3Ali%3Aperson%3Aabc`
6. **Polls cannot be updated** after creation
7. **`Linkedin-Version` header is mandatory** on every request — missing it returns an error
8. **Access tokens expire in 60 days** — no programmatic refresh for most apps
9. **Automation restriction** — LinkedIn API Terms of Use state "you must not use the APIs to automate posting." Enforced via the draft-then-publish pattern: every publish action requires a prior draft step, creating a natural review point where the user sees the content before it goes live.
10. **Mention format is strict** — `@[Name](urn:li:organization:ID)` must case-sensitively match the org's full name

## Not in Scope

- Organization page management (requires `w_organization_social` + admin role)
- LinkedIn Analytics / engagement metrics (requires restricted scopes)
- Scheduling posts (violates API Terms of Use for automation)
- Video upload (complex multi-part upload; add later if needed)
- LinkedIn Articles (long-form) publishing — distinct from share posts, limited API support
- Poll creation (low priority for promotion use case)

## Dependencies

- LinkedIn Developer Portal app with "Share on LinkedIn" and "Sign In with LinkedIn using OpenID Connect" products enabled
- `LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET` in `.env`
- npm packages: `@modelcontextprotocol/sdk`, `zod`, `undici`
- Existing `@micro-x-ai/mcp-shared` package for validation, logging, errors

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Developer Portal product approval delay | Cannot test until approved | Apply early; approval for "Share on LinkedIn" is typically fast |
| 60-day token expiry with no refresh | User must re-authenticate periodically | Clear error message with re-auth instructions; log expiry warnings |
| `r_member_social` scope restricted | Cannot read back own posts via API | Accept limitation; user can check LinkedIn directly |
| API Terms of Use on automation | Account risk if LinkedIn detects bot-like behavior | Draft-then-publish pattern enforces human review before every publish action |
| `Linkedin-Version` monthly rotation | Server breaks if version is sunsetted | Make version configurable via env; document update cadence |
