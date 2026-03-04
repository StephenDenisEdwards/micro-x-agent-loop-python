# Plan: dev.to Publishing MCP Server

**Status: Draft**

## Context

The agent needs a blog publishing channel for long-form technical content (white papers, architecture posts, cost analysis write-ups). dev.to is the best target: it accepts raw Markdown, has a simple API-key auth (no OAuth dance), and is where the AI/systems engineering audience reads technical content.

Medium's API is deprecated/limited, making dev.to the practical choice.

## Approach

Add a `devto` MCP server (TypeScript) that uses the dev.to (Forem) V1 API to create, update, and manage articles.

### API: Forem V1

**Base URL:** `https://dev.to/api`

**Required headers:**
```
api-key: {DEV_TO_API_KEY}
Accept: application/vnd.forem.api-v1+json
Content-Type: application/json
```

### Authentication

API key only — no OAuth. Obtain from dev.to Settings → Extensions → "DEV Community API Keys."

Simple, no token refresh needed, no expiry.

## Human-in-the-Loop: Draft-First Publishing

All publishing tools use a **draft-first** pattern for consistency with the other publishing MCP servers (LinkedIn, Reddit, X). See `PLAN-linkedin-publishing-mcp.md` for the full rationale.

dev.to has a natural advantage here: the API natively supports drafts (`published: false`). The workflow is:

1. **`devto_create_article`** — always creates as a draft (`published: false`), regardless of intent. Returns the article preview (title, body excerpt, tags, URL to draft on dev.to) plus the `article_id`.
2. The LLM shows the preview to the user for review. The user can also visit the draft URL on dev.to to see the full rendered version.
3. **`devto_publish_article`** — takes an `article_id` and sets `published: true` via `PUT /api/articles/{id}`.

Unlike the other publishing servers, dev.to drafts are server-side (stored on dev.to itself), not in-memory. This means drafts persist across sessions and have no TTL. The user can also edit drafts via the dev.to web UI before publishing.

## Tool Definitions

### `devto_create_article`

Create a new article as a draft on dev.to. Always creates as unpublished.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `title` | string | yes | Article title |
| `body_markdown` | string | yes | Article body in Markdown. Do NOT include an H1 — dev.to uses the `title` field separately |
| `tags` | string[] | no | Up to 4 tags (single words, no spaces) |
| `series` | string | no | Series name (creates or joins by name, no ID system) |
| `canonical_url` | string | no | Original source URL for cross-posts |
| `cover_image_url` | string | no | URL to externally hosted cover image (recommended: 1000x420px) |
| `description` | string | no | Short excerpt for feed cards |

**Endpoint:** `POST /api/articles`

**Payload structure:**
```json
{
  "article": {
    "title": "...",
    "body_markdown": "...",
    "published": false,
    "tags": ["python", "ai"],
    "series": "...",
    "canonical_url": "...",
    "main_image": "...",
    "description": "..."
  }
}
```

**Note:** The JSON field for cover image is `main_image`, not `cover_image`. The MCP tool parameter is named `cover_image_url` for clarity, mapped to `main_image` internally.

**Design:** The tool always sets `published: false`. There is no parameter to publish directly — use `devto_publish_article` after review.

**MCP annotations:** `readOnlyHint: false`, `destructiveHint: false`, `idempotentHint: false`

### `devto_publish_article`

Publish an existing draft article. This is the only tool that makes content publicly visible.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `article_id` | number | yes | Article ID (from `devto_create_article` or `devto_list_my_articles`) |

**Endpoint:** `PUT /api/articles/{id}` with `{ "article": { "published": true } }`

Returns the published article URL and stats.

**MCP annotations:** `readOnlyHint: false`, `destructiveHint: false`, `idempotentHint: true`

### `devto_update_article`

Update an existing article's content or metadata.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `article_id` | number | yes | Article ID (from create response or list) |
| `title` | string | no | New title |
| `body_markdown` | string | no | New body (replaces entire body) |
| `tags` | string[] | no | Replace tags |
| `series` | string | no | Change series |
| `canonical_url` | string | no | Update canonical URL |
| `cover_image_url` | string | no | Update cover image |
| `description` | string | no | Update description |

**Endpoint:** `PUT /api/articles/{id}`

**Note:** This tool does NOT change the `published` field. Use `devto_publish_article` to publish.

**Critical gotcha:** If the article's `body_markdown` contains YAML front matter, front matter values override JSON payload fields. When updating metadata, the server must either: (a) strip front matter from the body before sending, or (b) update the front matter within `body_markdown` itself.

**Design decision:** The server will NOT use YAML front matter. All metadata is passed via JSON payload fields. If an existing article has front matter (e.g., created via the web UI), the update tool will warn the user that front matter may override JSON fields.

**MCP annotations:** `readOnlyHint: false`, `destructiveHint: false`, `idempotentHint: true`

### `devto_list_my_articles`

List the authenticated user's articles.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `status` | string | no | `all` (default), `published`, or `draft` |
| `page` | number | no | Page number (default 1) |
| `per_page` | number | no | Results per page (default 30, max 1000) |

**Endpoints:**
- `all`: `GET /api/articles/me/all`
- `published`: `GET /api/articles/me/published`
- `draft`: `GET /api/articles/me/unpublished`

### `devto_get_article`

Get full details of a specific article.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `article_id` | number | yes | Article ID |

**Endpoint:** `GET /api/articles/{id}`

Returns full article including `body_markdown`, `body_html`, and stats (`page_views_count`, `public_reactions_count`, `comments_count`, `reading_time_minutes`).

**Note:** `page_views_count` is only present when fetching your own articles with authentication. Stats are updated once daily, not real-time.

### `devto_get_article_comments`

Get comments on an article.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `article_id` | number | yes | Article ID |

**Endpoint:** `GET /api/comments?a_id={article_id}`

## Output Schemas

### Article creation/update response
```json
{
  "id": 12345,
  "title": "My Article",
  "slug": "my-article-abc123",
  "url": "https://dev.to/username/my-article-abc123",
  "published": false,
  "tags": ["python", "ai"],
  "reading_time_minutes": 5,
  "page_views_count": 0,
  "public_reactions_count": 0,
  "comments_count": 0
}
```

### Article list response
```json
{
  "articles": [
    {
      "id": 12345,
      "title": "...",
      "url": "...",
      "published": true,
      "published_at": "2026-03-04T10:00:00Z",
      "tags": ["python"],
      "page_views_count": 1234,
      "public_reactions_count": 47,
      "comments_count": 12,
      "reading_time_minutes": 5
    }
  ],
  "count": 1
}
```

## Markdown Support

dev.to fully supports CommonMark/GitHub-flavored Markdown plus Liquid tag extensions for embeds:

```
{% youtube dQw4w9WgXcQ %}
{% github forem/forem %}
{% twitter 834439977220112384 %}
{% codepen https://codepen.io/... %}
```

Fenced code blocks with language identifiers are supported for syntax highlighting.

**Do NOT include an H1 (`# Title`) in the body** — dev.to renders the `title` field separately and will display a duplicate heading.

## Configuration

```json
{
  "McpServers": {
    "devto": {
      "command": "node",
      "args": ["mcp_servers/ts/packages/devto/dist/index.js"],
      "transport": "stdio",
      "env": {
        "DEV_TO_API_KEY": "${DEV_TO_API_KEY}"
      }
    }
  }
}
```

## Rate Limits

No official rate limit numbers are published. Observed behavior:
- Aggressive throttling — 429 errors common with sequential requests, especially on analytics endpoints
- Practical guidance: add 200ms+ delays between requests; 500ms-1s for analytics fetching
- A `Retry-After` header may be included on 429 responses

**Server design:** Implement sequential request execution (no parallel requests to dev.to) with 200ms minimum inter-request delay. Exponential backoff on 429s.

## Image Handling

**There is no image upload API.** All images must be externally hosted. The `cover_image_url` and inline images in Markdown must reference URLs to images hosted elsewhere (GitHub raw URLs, Cloudinary, imgbb, etc.).

**Implication for agent workflow:** When the agent needs to include images in a blog post, it must first upload them to an external host. This is out of scope for this MCP server — the agent can use existing file/web tools or a dedicated image hosting tool if added later.

## Key Gotchas

1. **Front matter overrides JSON payload.** If `body_markdown` contains YAML front matter, metadata fields in front matter take precedence over JSON fields in the request body.
2. **Maximum 4 tags per article.** Tags must be single words (no spaces). Exceeding 4 silently drops extras.
3. **No image upload API.** All images must be externally hosted.
4. **`body_markdown` is the correct field name** — not `content` (some older examples use the wrong name).
5. **Draft preview URLs are not public.** Drafts can only be viewed through the dev.to dashboard.
6. **Stats updated once daily.** `page_views_count` and reaction counts are not real-time.
7. **CORS disabled on authenticated endpoints.** Must be called server-side (not from browser). This is fine for an MCP server.
8. **`date` front matter field does nothing.** It does not schedule publication.
9. **V1 requires the `Accept: application/vnd.forem.api-v1+json` header** on all requests.

## Not in Scope

- Image upload/hosting (no API exists; use external hosts)
- Scheduled publishing (no API support; `date` field has no effect)
- Reaction management (liking/unicorning other articles)
- Reading list management
- Organization management
- Comment posting (read-only for now; add later if needed)
- Multi-image carousel or embedded media upload

## Dependencies

- dev.to account with API key generated
- `DEV_TO_API_KEY` in `.env`
- npm packages: `@modelcontextprotocol/sdk`, `zod`, `undici`
- Existing `@micro-x/mcp-shared` package

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Aggressive rate limiting with no documented limits | Batch operations unreliable | Sequential requests with 200ms delay; exponential backoff on 429 |
| Front matter overriding JSON fields on articles created via web UI | Update tool produces unexpected results | Detect front matter in body; warn user; document the behavior |
| API key compromise | Unauthorized access to dev.to account | Store key in `.env` (gitignored); key can be regenerated at any time |
| No image upload | Blog posts with images require extra steps | Document workaround (host on GitHub/Cloudinary); consider image hosting tool later |
