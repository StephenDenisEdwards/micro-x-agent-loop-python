# ADR-015: All Tools as TypeScript MCP Servers

## Status

Accepted

## Context

The agent loop had 29 built-in Python tools loaded via `tool_registry.py` plus 3 MCP servers (interview-assist, whatsapp, system-info). This split architecture created several problems:

1. **No structured data flow.** Built-in tools returned plain text strings. The LLM received unstructured output, and the orchestrator had no machine-parseable data for metrics, validation, or programmatic use (see ADR-014 for the original problem statement — now resolved with `ToolResult.structured` and `ToolResultFormatter`).

2. **No output validation.** Tools had no `outputSchema`, so there was no way to verify tool responses matched an expected shape.

3. **Tight coupling.** Adding, modifying, or testing a tool required changes to the Python agent loop codebase. Tool code lived alongside orchestration code with no process isolation.

4. **Credential sprawl.** `RuntimeEnv` carried 5 credential fields (Google, Brave, GitHub, Anthropic Admin) that were threaded through `bootstrap.py` → `tool_registry.py` → individual tool constructors.

5. **Inconsistent quality.** Each tool had its own error handling, logging, and input validation patterns. No shared infrastructure enforced consistency.

Options considered:

1. **Keep the split architecture** — continue maintaining both built-in Python tools and MCP servers
2. **Convert all tools to Python MCP servers** — same language, simpler porting
3. **Convert all tools to TypeScript MCP servers** — leverage the MCP TypeScript SDK's mature ecosystem, Zod for validation, better npm package availability for web/HTML/OAuth

## Decision

Convert all 29 built-in tools to 7 TypeScript MCP servers, grouped by credential boundary. Rewrite the existing Python interview-assist MCP server in TypeScript. Make the Python agent loop a pure MCP orchestrator with zero built-in tools.

### Server grouping

| Server | Tools | Credential |
|---|---|---|
| `filesystem` | bash, read_file, write_file, append_file, save_memory | FILESYSTEM_WORKING_DIR |
| `web` | web_fetch, web_search | BRAVE_API_KEY |
| `linkedin` | linkedin_jobs, linkedin_job_detail, linkedin_draft_post, linkedin_draft_article, linkedin_publish_draft | LINKEDIN_CLIENT_ID/SECRET |
| `x-twitter` | x_draft_tweet, x_draft_thread, x_publish_draft, x_delete_tweet, x_get_tweet, x_get_my_tweets, x_upload_media | X_CLIENT_ID/SECRET |
| `github` | list_prs, get_pr, create_pr, list_issues, create_issue, get_file, search_code, list_repos | GITHUB_TOKEN |
| `google` | gmail (3), calendar (3), contacts (6) | GOOGLE_CLIENT_ID/SECRET |
| `anthropic-admin` | usage | ANTHROPIC_ADMIN_API_KEY |
| `interview-assist` | ia_* (9), stt_* (5) | INTERVIEW_ASSIST_REPO |

### Key design choices

- **Shared package** (`@micro-x-ai/mcp-shared`): Zod validation, structured JSON stderr logging (pino), categorized errors, server factory — enforces consistent quality across all servers.
- **`outputSchema`** on every tool: Enables client-side validation and format-aware result presentation.
- **`structuredContent`** in every response: Machine-parseable JSON alongside human-readable `TextContent`. The orchestrator stores structured data for metrics/logging and formats it for the LLM context window using a configurable `ToolResultFormatter`.
- **MCP annotations** (`destructiveHint`, `readOnlyHint`): Propagated to `McpToolProxy.is_mutating` for the checkpoint system.
- **`ToolResult` dataclass**: Replaces the `str` return type on `execute()`. Carries `text`, `structured`, and `is_error`.
- **`ToolResultFormatter`**: Config-driven formatting of structured results into LLM-friendly text (json, table, key_value, text strategies). Per-tool config in `ToolFormatting` section.
- **Parallel server startup**: `McpManager.connect_all()` starts all server processes concurrently.
- **Credential isolation**: Each MCP server receives only its own credentials via `env` in the config. `RuntimeEnv` no longer carries tool-specific secrets.

### TypeScript over Python rationale

- The `@modelcontextprotocol/sdk` TypeScript SDK has better `outputSchema` and `structuredContent` support
- Zod provides tight schema validation with automatic JSON Schema generation
- npm ecosystem has better packages for the tool domains (cheerio, @octokit/rest, googleapis, mammoth)
- TypeScript's strict type system catches integration errors at compile time

## Consequences

### Positive

- **Structured data everywhere.** Every tool returns both `structuredContent` (JSON) and `content` (text). The orchestrator can format, validate, and log structured data independently.
- **Process isolation.** Tool crashes don't take down the agent loop. Each server can be restarted independently.
- **Consistent quality.** Shared validation, logging, and error handling across all tools.
- **Simplified orchestrator.** `bootstrap.py` no longer imports tool implementations. `tool_registry.py` and the entire `tools/` directory are deleted. `RuntimeEnv` has only 2 fields.
- **Configurable presentation.** `ToolFormatting` config controls how each tool's output appears in the LLM context window without changing tool code.

### Negative

- **Startup latency.** 7 Node.js processes must start before the agent is ready. Mitigated by parallel startup and pre-compiled JavaScript.
- **Operational complexity.** Debugging requires understanding both Python (orchestrator) and TypeScript (tools). `npm run build` required after tool changes.
- **Memory overhead.** Each Node.js process uses ~30-50MB RSS. 7 servers add ~250-350MB.

### Neutral

- Tool names change from `bash` to `filesystem__bash`. The LLM handles prefixed names without issue.
- The WhatsApp and system-info MCP servers remain unchanged (separate repos, different maintainers).
