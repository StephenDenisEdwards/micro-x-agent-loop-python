# Plan: Reimplement All Tools as TypeScript MCP Servers

**Status: Completed**

## Context

The agent loop currently has 29 built-in Python tools loaded via `tool_registry.py` plus 3 MCP servers (interview-assist, whatsapp, system-info). The best practices doc (`documentation/docs/best-practice/mcp-servers.md`) defines production standards that the current implementation doesn't meet:

- No `outputSchema` on any tool
- No `structuredContent` in responses
- No server-side validation against schemas
- No structured logging or audit trails
- No error categorization (validation vs upstream vs permission)
- Interview-assist server is a monolithic Python file with no separation of concerns

The goal is to:

1. Convert all 29 built-in tools to TypeScript MCP servers
2. Rewrite the existing interview-assist Python MCP server in TypeScript
3. Update the Python agent loop to be a pure MCP orchestrator (no built-in tools)
4. Update the Tool Protocol to return structured data (`ToolResult`) instead of `str`
5. Apply all best practices from the doc

## Data Flow: Structured Content and LLM Presentation

**Principle:** MCP servers return data. The agent loop decides how to present it to the LLM.

### Server responsibility (MCP layer)
- Return `structuredContent` with the full typed JSON result
- Return a `TextContent` block containing the serialized JSON (per spec's backwards-compatibility SHOULD)
- Validate output against `outputSchema` before returning
- No LLM-specific formatting, summarization, or presentation logic — the server has no knowledge of or coupling to any specific LLM or context window

### Client responsibility (agent loop)
- Receive both `structuredContent` and `content[].text` from the MCP response
- Store `structuredContent` in `ToolResult.structured` for programmatic use (metrics, logging, validation, memory)
- **Format** the tool result text sent to the LLM using a **per-tool configurable strategy**
- This keeps MCP servers as clean data layers and keeps all presentation/formatting logic in the orchestrator where it belongs

### Formatting strategy: per-tool configuration

Each tool's LLM presentation format is specified in config, not hardcoded. The config maps tool names to a formatting strategy that controls how `structuredContent` is transformed into the text string placed in the LLM's tool_result message.

**Config structure** (in `McpServers` section or a dedicated `ToolFormatting` section):
```json
{
  "ToolFormatting": {
    "github__list_prs": { "format": "table", "max_rows": 20 },
    "github__get_pr": { "format": "json" },
    "gmail__search": { "format": "table", "max_rows": 15 },
    "gmail__read": { "format": "json" },
    "filesystem__bash": { "format": "text", "field": "stdout" },
    "filesystem__read_file": { "format": "text", "field": "content" }
  },
  "DefaultFormat": { "format": "json" }
}
```

**Available format strategies:**
- `"json"` — `json.dumps(structuredContent, indent=2)` + truncation. Default when no config specified.
- `"table"` — Renders arrays of objects as a compact markdown table. Column headers from `outputSchema` property names. Optional `max_rows` limit.
- `"text"` — Extracts a single text field from the structured result (e.g., `stdout` from bash, `content` from read_file). Useful when the primary payload is a string inside a wrapper object.
- `"key_value"` — Renders a flat object as `key: value` pairs, one per line. Compact for simple status/metadata responses.

**Implementation:** A `ToolResultFormatter` component in the agent loop:
- Takes `ToolResult.structured`, `outputSchema`, and the tool's format config
- Produces the text string for the LLM context window
- Falls back to `ToolResult.text` (the server's TextContent) if no `structuredContent` is present
- Applies `max_tool_result_chars` truncation after formatting

This approach gives full control over per-tool presentation without coupling format logic to the MCP server or the tool implementation. New format strategies can be added over time without changing servers or tools.

## Server Grouping

Seven first-party MCP servers, grouped by credential boundary and domain:

| Server | Tool Count | Tools | Credential |
|---|---|---|---|
| `filesystem` | 5 | bash, read_file, write_file, append_file, save_memory | FILESYSTEM_WORKING_DIR, USER_MEMORY_DIR |
| `web` | 2 | web_fetch, web_search | BRAVE_API_KEY |
| `linkedin` | 2 | linkedin_jobs, linkedin_job_detail | (none -- scraping) |
| `google` | 12 | gmail_search/read/send, calendar_list/create/get, contacts_search/list/get/create/update/delete | GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET |
| `github` | 8 | list_prs, get_pr, create_pr, list_issues, create_issue, get_file, search_code, list_repos | GITHUB_TOKEN |
| `anthropic-admin` | 1 | anthropic_usage | ANTHROPIC_ADMIN_API_KEY |
| `interview-assist` | 16 | ia_healthcheck, ia_list_recordings, ia_analyze_session, ia_evaluate_session, ia_compare_strategies, ia_tune_threshold, ia_regression_test, ia_create_baseline, ia_transcribe_once, stt_list_devices, stt_start_session, stt_get_updates, stt_get_session, stt_stop_session | INTERVIEW_ASSIST_REPO |

**Grouping rationale:** Each server maps to a single credential/auth boundary. Tools that share an API client or OAuth flow belong in the same server. This minimizes the number of processes while keeping credential isolation clean.

**Out of scope:** The WhatsApp MCP server remains in its separate repo per ADR-006 (third-party, different maintainer, Go+Python toolchain).

## Project Structure

TypeScript monorepo using npm workspaces, co-located in this repository under `mcp_servers/ts/`. First-party servers share a workspace (unlike third-party servers which go in separate repos per ADR-006).

```
mcp_servers/ts/
  package.json                    # npm workspaces root
  tsconfig.base.json              # shared TS compiler config
  packages/
    shared/                       # @micro-x/mcp-shared
      package.json
      src/
        index.ts
        validation.ts             # Zod-based input/output schema validation
        logging.ts                # Structured JSON stderr logger
        errors.ts                 # ValidationError, UpstreamError, PermissionError
        server-factory.ts         # stdio/HTTP dual-transport factory
        schemas.ts                # Reusable schema fragments (pagination, paths)
    filesystem/
      package.json
      src/
        index.ts                  # Server entry point
        tools/
          bash.ts
          read-file.ts
          write-file.ts
          append-file.ts
          save-memory.ts
    web/
      package.json
      src/
        index.ts
        tools/
          web-fetch.ts
          web-search.ts
    linkedin/
      package.json
      src/
        index.ts
        tools/
          linkedin-jobs.ts
          linkedin-job-detail.ts
    google/
      package.json
      src/
        index.ts
        auth/
          google-auth.ts          # Unified OAuth2 for all Google APIs
        tools/
          gmail-search.ts
          gmail-read.ts
          gmail-send.ts
          calendar-list-events.ts
          calendar-create-event.ts
          calendar-get-event.ts
          contacts-search.ts
          contacts-list.ts
          contacts-get.ts
          contacts-create.ts
          contacts-update.ts
          contacts-delete.ts
    github/
      package.json
      src/
        index.ts
        tools/
          list-prs.ts
          get-pr.ts
          create-pr.ts
          list-issues.ts
          create-issue.ts
          get-file.ts
          search-code.ts
          list-repos.ts
    anthropic-admin/
      package.json
      src/
        index.ts
        tools/
          usage.ts
    interview-assist/
      package.json
      src/
        index.ts
        tools/
          healthcheck.ts
          list-recordings.ts
          analyze-session.ts
          evaluate-session.ts
          compare-strategies.ts
          tune-threshold.ts
          regression-test.ts
          create-baseline.ts
          transcribe-once.ts
          stt-list-devices.ts
          stt-start-session.ts
          stt-get-updates.ts
          stt-get-session.ts
          stt-stop-session.ts
```

## Shared Package Design (`@micro-x/mcp-shared`)

Implements the cross-cutting best practices from `mcp-servers.md`:

### `validation.ts`
- `validateInput(schema, data)` -- Zod-based validation against inputSchema; returns typed result or throws `ValidationError`
- `validateOutput(schema, data)` -- Validates tool outputs against outputSchema before returning
- All schemas enforce `additionalProperties: false` by default

### `logging.ts`
- JSON lines to **stderr** (never stdout -- critical for stdio mode)
- Fields: `timestamp`, `request_id`, `tool_name`, `duration_ms`, `outcome`, `level`
- Audit log helper for side-effectful operations (writes, sends, deletes)
- Correlates MCP request id with internal trace id

### `errors.ts`
- `ValidationError` -- bad input from LLM (maps to `isError: true` with actionable message)
- `UpstreamError` -- external API failure (includes status code, retryable flag)
- `PermissionError` -- credential/authorization failure
- `TimeoutError` -- operation exceeded limit
- Each maps to appropriate MCP error response format

### `server-factory.ts`
- Factory function: takes tool handler map, produces MCP server with stdio (default) or HTTP transport
- Wires in validation middleware, structured logging, error handling
- Configures `tools/list` responses with both `inputSchema` and `outputSchema`
- Sets MCP tool annotations: `readOnlyHint`, `destructiveHint`, `idempotentHint`

### `schemas.ts`
- Reusable schema fragments: pagination (pageSize, offset), file paths, result envelopes
- Common Zod patterns shared across servers

## Phases

### Phase 0: Foundation (Shared Package + Validation)

Create the TS monorepo, shared package, and a minimal "echo" MCP server to validate end-to-end stdio integration with the existing Python `McpManager`.

**Deliverables:**
- `mcp_servers/ts/` monorepo with npm workspaces
- `@micro-x/mcp-shared` package (validation, logging, errors, server-factory)
- Echo MCP server: one dummy tool that returns structuredContent
- Config entry added to verify McpManager discovers and calls it

**Verification:**
- Echo server starts via stdio, McpManager discovers tool, agent calls it
- Structured logs appear on stderr, nothing on stdout
- structuredContent present in MCP response (Python SDK v1.26.0 supports it)

**Key dependencies:** `@modelcontextprotocol/sdk`, `zod`, `pino`

---

### Phase 1: Filesystem Server (establishes template)

Port bash, read_file, write_file, append_file, save_memory. This is the simplest server (no external APIs, no auth) and establishes the pattern all subsequent servers follow.

**Port notes per tool:**

| Tool | Source | Key porting concerns |
|---|---|---|
| `bash` | `tools/bash_tool.py` | Windows/Unix detection (`_IS_WINDOWS`), 30s timeout, stdout+stderr merge, exit code. Use `child_process.execFile`. Keep `bash_command_parser.py` on Python client side (checkpoint concern, not tool concern). |
| `read_file` | `tools/read_file_tool.py` | Text + .docx support (use `mammoth` npm). Working directory resolution via FILESYSTEM_WORKING_DIR env. |
| `write_file` | `tools/write_file_tool.py` | Auto-create parent directories. Path resolution from working directory. |
| `append_file` | `tools/append_file_tool.py` | Existence check (error if file doesn't exist). |
| `save_memory` | `tools/save_memory_tool.py` | .md-only sandbox, path traversal prevention, line-count warning. USER_MEMORY_DIR + USER_MEMORY_MAX_LINES env vars. |

**Every tool gets:** tight `inputSchema` (`additionalProperties: false`), `outputSchema`, `structuredContent` response, Zod validation on both input and output, structured logging, MCP annotations.

**Migration step:** Add filesystem server to config alongside built-in tools. Verify identical behavior. Remove built-in versions from `tool_registry.py`.

---

### Phase 2: Web Server

Port web_fetch and web_search.

| Tool | Source | Key porting concerns |
|---|---|---|
| `web_fetch` | `tools/web/web_fetch_tool.py` | HTTP client (undici), HTML-to-text (cheerio -- port `html_utilities.py` BeautifulSoup logic: strip scripts/styles, preserve links, handle lists/tables, normalize whitespace), JSON pretty-print, 2MB response limit, 50KB truncation. |
| `web_search` | `tools/web/web_search_tool.py` | Brave Search API. BRAVE_API_KEY env. Return structured JSON array of `SearchResult` objects (not formatted text). Port `BraveSearchProvider` as separate module. |

---

### Phase 3: LinkedIn Server

Port linkedin_jobs, linkedin_job_detail.

| Tool | Source | Key porting concerns |
|---|---|---|
| `linkedin_jobs` | `tools/linkedin/linkedin_jobs_tool.py` | HTML scraping of LinkedIn public guest API with cheerio. CSS selectors for card parsing. User-Agent spoofing required. Fragile -- document scraping risk. |
| `linkedin_job_detail` | `tools/linkedin/linkedin_job_detail_tool.py` | Fetch and parse individual job posting page. |

---

### Phase 4: GitHub Server

Port 8 tools. Use `@octokit/rest` (official TS SDK with pagination, rate limiting, retries) instead of raw HTTP (current Python uses raw httpx).

| Tool | Source | Key porting concerns |
|---|---|---|
| `list_prs` | `tools/github/github_list_prs_tool.py` | Uses `/search/issues` API for author filtering (line 93-106). Structured JSON output replaces `_format_prs()` text formatting. |
| `get_pr` | `tools/github/github_get_pr_tool.py` | Single PR detail fetch. |
| `create_pr` | `tools/github/github_create_pr_tool.py` | Side-effectful -- needs audit logging + `destructiveHint` annotation. |
| `list_issues` | `tools/github/github_list_issues_tool.py` | Filters: repo, state, creator, assignee. |
| `create_issue` | `tools/github/github_create_issue_tool.py` | Side-effectful. |
| `get_file` | `tools/github/github_get_file_tool.py` | Raw content fetch, base64 for binary. |
| `search_code` | `tools/github/github_search_code_tool.py` | GitHub code search query syntax. |
| `list_repos` | `tools/github/github_list_repos_tool.py` | User's accessible repos. |

GITHUB_TOKEN passed via env. Instantiate Octokit once at server startup.

---

### Phase 5: Google Server

Port 12 tools. Most complex phase due to OAuth2 flows.

**Auth architecture:**
- Unified OAuth2 module using `googleapis` + `google-auth-library` npm packages
- Single consent flow requesting all scopes (Gmail, Calendar, People API)
- Token persistence in existing paths (`.gmail-tokens/`, `.calendar-tokens/`, `.contacts-tokens/`)
- GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET via env
- `google-auth-library` provides `OAuth2Client` with local server redirect (equivalent to Python's `InstalledAppFlow.run_local_server(port=0)`)

**Tools:** gmail_search, gmail_read, gmail_send, calendar_list_events, calendar_create_event, calendar_get_event, contacts_search, contacts_list, contacts_get, contacts_create, contacts_update, contacts_delete.

**Port notes:**
- Gmail: metadata format for search, full format for read. Port `gmail_parser.py` header extraction.
- Calendar: ISO 8601 time ranges, multi-calendar support.
- Contacts: Port `contacts_formatter.py`. People API v1.
- gmail_send, calendar_create_event, contacts_create/update/delete are side-effectful -- audit logging.

**Risk:** OAuth2 flow in TS differs from Python. Prototype the auth module early in this phase before implementing tools.

---

### Phase 6: Anthropic Admin Server

Port anthropic_usage (1 tool). Simplest server.

- HTTP client to Anthropic Admin API. ANTHROPIC_ADMIN_API_KEY env.
- Three actions: `usage` (token-level), `cost` (USD -- port `_convert_cost_amounts` cents-to-dollars logic), `claude_code` (productivity metrics).
- Structured output with typed report shapes.

---

### Phase 7: Interview Assist Server (rewrite from Python)

Rewrite `mcp_servers/interview_assist_server.py` in TypeScript.

**Key porting concerns:**
- .NET CLI subprocess management: `child_process.spawn()` replaces `subprocess.Popen`
- STT session state: `Map<string, SttSession>` replaces Python dataclass + threading
- Streaming capture loop (`_stt_capture_loop`, lines 123-224): reads JSON lines from .NET CLI stdout, emits events. Port to Node.js readline interface on child process stdout.
- Repo validation (`_resolve_repo`): check .NET project paths exist.
- INTERVIEW_ASSIST_REPO env var for .NET repo path.

**16 tools to port:** ia_healthcheck, ia_list_recordings, ia_analyze_session, ia_evaluate_session, ia_compare_strategies, ia_tune_threshold, ia_regression_test, ia_create_baseline, ia_transcribe_once, stt_list_devices, stt_start_session, stt_get_updates, stt_get_session, stt_stop_session.

---

### Phase 8: Client-Side Cleanup + Final Migration

Update the Python agent loop to be MCP-only.

**8a. Update Tool Protocol** (`src/micro_x_agent_loop/tool.py`):
```python
@dataclass
class ToolResult:
    text: str                           # Human-readable (for context window)
    structured: dict[str, Any] | None = None  # Machine-parseable JSON
    is_error: bool = False
```
Change `execute()` return type from `str` to `ToolResult`.

**8b. Update McpToolProxy** (`src/micro_x_agent_loop/mcp/mcp_tool_proxy.py`):
- Read `result.structuredContent` from MCP response (already supported in MCP Python SDK v1.26.0)
- Populate `ToolResult.structured` when `structuredContent` is present
- Populate `ToolResult.text` from `content[].text` (the server's serialized JSON fallback)
- Store `outputSchema` from tool definition (captured at discovery time in McpManager)

**8c. Update McpManager** (`src/micro_x_agent_loop/mcp/mcp_manager.py`):
- Capture `outputSchema` from tool definitions during `tools/list` discovery
- Pass `outputSchema` through to McpToolProxy so it's available for client-side formatting
- Parallelize server startup (currently sequential in `connect_all()`)

**8d. Add ToolResultFormatter**:
- New component that formats `ToolResult.structured` into text for the LLM context window
- Reads per-tool format config from `ToolFormatting` section in config (format strategy, options like `max_rows`, `field`)
- Implements format strategies: `json`, `table`, `key_value`, `text`
- Falls back to `ToolResult.text` (the server's TextContent) when no `structuredContent` is present
- Falls back to `DefaultFormat` (json) when no per-tool config exists
- Applies `max_tool_result_chars` truncation after formatting
- `result.structured` is preserved separately for metrics, logging, memory, and validation — never goes through formatting/truncation

**8e. Update bootstrap.py** (`src/micro_x_agent_loop/bootstrap.py`):
- Remove `get_all()` call (line 41-48) -- no more built-in tools
- All tools come from `mcp_manager.connect_all()`
- Remove conditional `SaveMemoryTool` import (line 120-122) -- now in filesystem MCP server
- Simplify `AppRuntime` (remove `builtin_tools` field)

**8f. Remove dead code:**
- Delete entire `src/micro_x_agent_loop/tools/` directory (all 29 tool files + auth modules + utilities)
- Delete `src/micro_x_agent_loop/tool_registry.py`
- Simplify `RuntimeEnv` in `app_config.py` (remove google_client_id, google_client_secret, brave_api_key, github_token, anthropic_admin_api_key -- these now flow via MCP server env config)

**8g. Update config files:**
- All `config*.json` get full `McpServers` entries for the 7 new TypeScript servers
- Each entry specifies: `command: "node"`, `args: ["mcp_servers/ts/packages/{server}/dist/index.js"]`, `transport: "stdio"`, `env: {...credentials...}`

**8h. Documentation:**
- Write ADR for this migration decision
- Update relevant design docs

## Migration Strategy

**Additive then subtractive** -- for each server:

1. Implement the TS MCP server
2. Add it to `McpServers` in config -- tools appear as `{server}__{tool}` (e.g., `filesystem__bash`)
3. Both old (built-in `bash`) and new (MCP `filesystem__bash`) coexist temporarily
4. Verify MCP version works identically
5. Remove the built-in version from `tool_registry.py`
6. MCP tool is now the only version

**Tool naming:** Keep `{server}__{tool}` prefix (current behavior in `McpToolProxy.name`, line 21). Prevents collisions if multiple servers define same-named tools. The LLM handles prefixed names fine.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Startup latency (7 Node.js processes) | Agent startup slower | Pre-compile TS to JS; parallelize startup in McpManager; consider lazy connect on first tool use |
| Google OAuth2 flow differs in TS | Phase 5 blocks | Prototype auth module early before implementing tools |
| LinkedIn scraping breaks during port | LinkedIn tools unusable | Keep Python fallback until TS version verified; scraping is inherently fragile |
| STT session state complexity in Node.js vs Python threading | Interview-assist reliability | Use Node.js async subprocess management with readline; thorough testing |
| Windows path handling differences | File tools break on Windows | Use `path.resolve()`/`path.join()` consistently; test on Windows explicitly |
| MCP Python SDK structuredContent compatibility | Structured data not available | Already confirmed: SDK v1.26.0 has `CallToolResult.structuredContent` |

## Key Dependencies Per Server

| Server | Key npm packages |
|---|---|
| shared | `@modelcontextprotocol/sdk`, `zod`, `pino` |
| filesystem | shared, `mammoth` (docx) |
| web | shared, `undici`, `cheerio` |
| linkedin | shared, `undici`, `cheerio` |
| google | shared, `googleapis`, `google-auth-library` |
| github | shared, `@octokit/rest` |
| anthropic-admin | shared, `undici` |
| interview-assist | shared (uses `child_process` built-in) |

## Key Files Modified/Deleted

| File | Change |
|---|---|
| `src/micro_x_agent_loop/tool.py` | Add `ToolResult` dataclass, update `Tool` Protocol return type |
| `src/micro_x_agent_loop/mcp/mcp_tool_proxy.py` | Handle `structuredContent`, store `outputSchema` |
| `src/micro_x_agent_loop/mcp/mcp_manager.py` | Forward `outputSchema`, parallelize startup |
| `src/micro_x_agent_loop/bootstrap.py` | Remove `get_all()`, MCP-only loading, remove `SaveMemoryTool` import |
| `src/micro_x_agent_loop/app_config.py` | Simplify `RuntimeEnv` (remove credential fields) |
| `src/micro_x_agent_loop/tool_registry.py` | Progressively emptied, then deleted |
| `src/micro_x_agent_loop/tools/*` | Progressively deleted (all 29 tool files) |
| `config*.json` | Add `McpServers` entries for 7 TS servers |
| `mcp_servers/interview_assist_server.py` | Deleted (replaced by TS version) |
