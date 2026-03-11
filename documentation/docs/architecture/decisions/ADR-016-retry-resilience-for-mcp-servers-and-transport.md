# ADR-016: Retry/Resilience for MCP Servers and Transport

## Status

Accepted

## Context

All MCP tool calls flow through two boundaries that can fail transiently:

1. **HTTP calls inside TypeScript MCP servers** — the server makes HTTP requests to external APIs (GitHub, LinkedIn, Brave Search, arbitrary web pages). These fail on 429 rate limits, 502/503/504 gateway errors, network timeouts, and DNS blips.
2. **MCP stdio transport between Python orchestrator and TypeScript servers** — the stdio pipe can break if a server process crashes, runs out of memory, or stalls.

Before this change, every transient failure was terminal: the tool returned an error to the LLM, which either gave up or retried the entire tool call (wasting a full LLM turn). LinkedIn tools had no timeouts at all — a hung connection would block forever.

### Design constraint: no duplicate retry

Each failure type must be retried at exactly one layer. HTTP errors are retried in TypeScript (where response headers like `Retry-After` are visible). Transport errors are retried in Python (where the stdio pipe state is visible). Application-level errors (`isError: true` in MCP) are never retried — the server successfully processed the request and determined it failed.

## Decision

Implement two retry layers using established libraries — no hand-rolled retry logic.

### Layer A: HTTP retry in TypeScript MCP servers

**Library: `p-retry`** (25M+ weekly downloads, exponential backoff, jitter, abort support)

`resilientFetch()` in `@micro-x/mcp-shared` wraps `fetch()` with:
- `AbortController` timeout (configurable, default 30s)
- Automatic retry via `p-retry` on transient status codes (429, 500, 502, 503, 504), network `TypeError`s, and timeout `AbortError`s
- `Retry-After` and `x-ratelimit-reset` header parsing on 429 responses — the retry delay respects server-requested wait times
- Defaults: 3 retries, 1-30s exponential backoff with jitter

Used by: LinkedIn tools (15s timeout), Web tools (30s timeout).

**Library: `@octokit/plugin-retry` + `@octokit/plugin-throttling`** (Octokit's official plugins)

GitHub uses Octokit's plugin system instead of `resilientFetch` because Octokit manages its own request pipeline. The plugins handle:
- Primary rate limit: retry up to 3x, respects `Retry-After`
- Secondary (abuse) rate limit: retry up to 2x

All 8 GitHub tool files benefit automatically with zero individual changes.

**Not changed:** Google MCP server — `googleapis` has built-in retry via `gaxios`.

### Layer B: MCP transport retry in Python `McpClient`

**Library: `tenacity`** (already a project dependency, see ADR-002)

`@retry` decorator on `McpClient.call_tool()`:
- Retries on transport errors only: `ConnectionError`, `BrokenPipeError`, `OSError`, `asyncio.TimeoutError`
- Does NOT retry `RuntimeError` from `isError=true` — that's a valid application-level error
- 3 attempts, exponential wait 1-10s
- Logs retries at WARNING level via `before_sleep_log`

### Error classification

| Error | Transient? | Retried where |
|---|---|---|
| HTTP 429/500/502/503/504 | Yes | TS server (`resilientFetch` / Octokit plugins) |
| Network timeout / DNS failure | Yes | TS server (`resilientFetch`) |
| HTTP 400/401/403/404/422 | No | Not retried |
| MCP stdio pipe break | Yes | Python `McpClient` (tenacity) |
| MCP `isError: true` response | No | Not retried |

### Files

| File | Change |
|---|---|
| `packages/shared/src/retry.ts` | New — `resilientFetch`, `isTransientStatusCode`, `isTransientError` |
| `packages/shared/src/errors.ts` | Added `retryAfterMs` to `UpstreamError` |
| `packages/shared/src/index.ts` | Exports retry utilities |
| `packages/github/src/github-client.ts` | Octokit plugin wiring |
| `packages/linkedin/src/tools/linkedin-jobs.ts` | `fetch` → `resilientFetch` |
| `packages/linkedin/src/tools/linkedin-job-detail.ts` | `fetch` → `resilientFetch` |
| `packages/web/src/tools/web-fetch.ts` | Manual timeout+fetch → `resilientFetch` |
| `packages/web/src/tools/web-search.ts` | Manual timeout+fetch → `resilientFetch` |
| `tools/template-py/mcp_client.py` | tenacity `@retry` on `call_tool()` |

## Consequences

### Positive

- Transient HTTP failures recover automatically without wasting LLM turns
- LinkedIn tools now have timeouts (previously could hang indefinitely)
- Web tools have simpler code — manual `AbortController`+`setTimeout`+`try/catch` replaced by a single `resilientFetch` call
- Rate limit headers (`Retry-After`, `x-ratelimit-reset`) are respected, avoiding ban escalation
- MCP server process crashes don't immediately fail the tool call

### Negative

- Additional dependencies: `p-retry` (shared), `@octokit/plugin-retry` + `@octokit/plugin-throttling` (github)
- Retry delays add latency on transient failures (up to ~30s per tool call in worst case)
- Transport retry on `call_tool()` may re-execute a tool that partially succeeded (acceptable for read-only tools; mutating tools like `create_pr` could theoretically create duplicates, though MCP servers are designed to be idempotent)
