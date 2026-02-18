# Plan: Add `web_fetch` Tool

**Status: Completed** (2026-02-18)

## Context

The agent currently has no way to fetch web content. When tasks require reading articles, documentation, job listings, or API responses from URLs, the agent can't access them unless they arrive via Gmail or LinkedIn tools. Adding a general-purpose `web_fetch` tool unlocks a large class of use cases with minimal complexity.

This is Phase 1 of a broader web interaction roadmap (Phase 2: web search, Phase 3: browser automation). The design mirrors OpenClaw's `web_fetch` approach, adapted to this project's minimal Python patterns.

## Dependencies

**No new dependencies required.** The project already has:
- `httpx>=0.27.0` — async HTTP client (used by LinkedIn tools)
- `beautifulsoup4>=4.12.0` + `lxml>=5.0.0` — HTML parsing (used by LinkedIn tools + `html_utilities.py`)

## New File

### `src/micro_x_agent_loop/tools/web/web_fetch_tool.py`

Single tool class following the existing `Tool` protocol pattern (same as `LinkedInJobDetailTool`).

**Input schema:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | yes | — | HTTP or HTTPS URL to fetch |
| `maxChars` | number | no | `50000` | Max characters to return (truncates with warning) |

**Behaviour:**

1. **Validate URL** — must be http(s), reject other schemes
2. **Fetch** — `httpx.AsyncClient.get()` with browser-like User-Agent, 30s timeout, follow redirects (max 5)
3. **Extract content** based on Content-Type:
   - `text/html` → use existing `html_to_text()` from `html_utilities.py` for plain-text extraction (with preserved links)
   - `application/json` → `json.dumps(indent=2)` pretty-print
   - Everything else → raw text
4. **Truncate** if content exceeds `maxChars`, append truncation notice
5. **Return** structured text with metadata header:
   ```
   URL: https://example.com/page
   Final URL: https://example.com/page (after redirects)
   Status: 200
   Content-Type: text/html
   Title: Page Title
   Length: 12,345 chars (truncated from 85,000)

   --- Content ---

   [extracted text]
   ```

**Error handling** (return error string, don't raise):
- Invalid URL → `"Error: URL must use http or https scheme"`
- Timeout → `"Error: Request timed out after 30 seconds"`
- HTTP errors → `"Error: HTTP {status_code} fetching {url}"`
- Network errors → `"Error: {exception description}"`

**Constants:**
- `_DEFAULT_MAX_CHARS = 50_000`
- `_MAX_RESPONSE_BYTES = 2_000_000` (2 MB, reject larger responses)
- `_TIMEOUT_SECONDS = 30`
- `_MAX_REDIRECTS = 5`
- Reuse `_USER_AGENT` / `_HEADERS` pattern from `linkedin_job_detail_tool.py`

**Title extraction** — for HTML pages, pull `<title>` tag text before converting to plain text.

## Changes to Existing Files

### `src/micro_x_agent_loop/tool_registry.py`
- Import `WebFetchTool`
- Add `WebFetchTool()` to the unconditional tools list (no credentials needed)

## Files Referenced (no changes needed)

| File | Reuse |
|------|-------|
| `src/micro_x_agent_loop/tool.py` | `Tool` protocol — the interface to implement |
| `src/micro_x_agent_loop/tools/html_utilities.py` | `html_to_text()` for HTML→text extraction |
| `src/micro_x_agent_loop/tools/linkedin/linkedin_job_detail_tool.py` | Reference pattern for httpx usage, User-Agent, error handling |

## Not in Scope (intentionally)

- **Caching** — keep it simple for now; add later if needed
- **Markdown extraction mode** — `html_to_text()` already preserves links and structure; a markdown mode can be added later
- **Firecrawl fallback** — unnecessary complexity for Phase 1
- **SSRF protection** — the agent runs locally as a personal tool; not exposed to untrusted input
- **POST/PUT support** — GET only for now; extend later if needed

## Verification

1. **Basic fetch**: `web_fetch` with a public URL → returns page content with metadata header
2. **JSON API**: Fetch a JSON endpoint → returns pretty-printed JSON
3. **Truncation**: Fetch a large page with `maxChars: 500` → content truncated with notice
4. **Invalid URL**: Pass `ftp://example.com` → returns descriptive error
5. **Timeout/error**: Fetch non-existent domain → returns timeout/network error
6. **Redirect**: Fetch URL that redirects → final URL shown in metadata
7. **Tool registered**: Appears in startup banner tool list

## Future Phases

- **Phase 2: `web_search`** — Brave Search API integration for agent-driven research
- **Phase 3: `browser`** — Playwright-based browser automation for JS-heavy sites and form interaction
- **Phase 4: Session management** — Cookie persistence, login flows, browser profiles
