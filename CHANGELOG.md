# Changelog

All notable changes to micro-x-agent-loop-python are documented here, grouped by feature area.

## 2026-05-09

### Features
- **FS-navigation directive in the system prompt + opinionated tool descriptions.** New `_FS_NAVIGATION_DIRECTIVE` (in `system_prompt.py`) tells the model to reach for `read_file` / `grep` / `glob` / `edit_file` / `write_file` / `append_file` instead of `bash cat` / `grep` / `find` / `sed` / `echo >`. Calls out parallel execution (`asyncio.gather`), the 3-grep-query threshold for spawning an `explore` sub-agent, and the read_file → quote → edit_file editing workflow. Tool descriptions for `bash` (was one line), `glob` (was two lines), and `grep` (now documents the three output modes by name) rewritten in the same opinionated style as the existing `grep` description so the model picks the right tool from the description alone. Closes Phase 1 of [PLAN-filesystem-navigation](documentation/docs/planning/PLAN-filesystem-navigation.md).
- **`edit_file` MCP tool — surgical exact-string edits to existing files.** New first-party tool in the filesystem MCP server. Replaces `old_string` with `new_string`; uniqueness is enforced (set `replace_all=true` to apply to every match, or include more surrounding context). CRLF/LF line endings are detected from the file and `old_string` / `new_string` are normalised to match — critical for editing CRLF files with LF-default model output (Windows-primary codebase). UTF-8 BOM preserved. Binary files refused (null-byte sniff). Files larger than 5 MB refused (override via `FILESYSTEM_EDIT_MAX_BYTES`). Atomic write via same-directory temp + `rename`. Mutations are checkpointed by the agent's `_MUTATING_TOOL_NAMES` machinery so `/rewind` restores edits. Closes Phase 2 of [PLAN-filesystem-navigation](documentation/docs/planning/PLAN-filesystem-navigation.md).
- **`read_file` now returns `cat -n`-style line-numbered text with `offset` / `limit` parameters.** Default returns up to 2000 lines from line 1; pass `offset` / `limit` to read a specific window. Truncation marker (`[truncated at line N of M — use offset=N+1 to continue]`) tells the model when there's more. Empty files return `(file is empty)`; offsets past EOF return a clear hint. Binary files (null byte in the first 8 KB) are refused with an explicit error rather than dumping raw bytes. `.docx` extraction is unchanged but now line-numbered. Quoting `<path>:<line>` from the output is now natural — important groundwork for `edit_file`. **Backwards-incompatible** for any consumer that relied on the raw text format of the `text` content block; the agent and codegen subprocess do not, so no in-tree caller is affected.

### Behavioural changes (potentially breaking)
- **`write_file`, `append_file`, and `read_file` now enforce path containment.** All three tools route paths through `PathPolicy` (`resolveAllowed` with `realpath`). Absolute paths outside `FILESYSTEM_WORKING_DIR` and `FILESYSTEM_ALLOWED_DIRS` are now rejected with an error naming the env var; symlinks pointing out of the allowed roots are also rejected. Closes the asymmetry flagged in [ISSUE-005](documentation/docs/issues/ISSUE-005-bash-tool-bypasses-path-policy.md) §75 (search tools were gated; file tools were open). `bash` remains unconstrained — see ISSUE-005 for the threat-model statement. Workflows that read or wrote outside the workspace via these tools need to add the extra root to `FILESYSTEM_ALLOWED_DIRS`.

## 2026-03-04

### Features
- **Interactive mode selection** — When compiled-mode signals are detected in a user prompt, the agent now explains what it found and asks the user to choose between PROMPT and COMPILED mode before proceeding
- **LinkedIn publishing tools** — Added `draft-post`, `draft-article`, and `publish-draft` tools for LinkedIn content creation
- **`/tools mcp` command** — New command shows hierarchical tool listing grouped by MCP server
- **Ask-user pseudo-tool** — LLM can now pause and ask the user clarifying questions with arrow-key selection (ADR-017)
- **Startup logo** — ASCII art branding shown at agent startup

### Docs
- Split README into promotional README and practical QUICKSTART
- Updated SAD to v3.0 with architecture diagrams

## 2026-03-03

### Features
- **MCP retry/resilience** — MCP server connections and tool calls now retry on transient failures with exponential backoff (ADR-016)
- **GitHub structured content** — GitHub MCP tools return structured content with metadata
- **On-demand tool search** — Large tool sets are deferred and discovered by the LLM via `tool_search`
- **Codegen prompt discipline** — Tightened code generation prompts with infrastructure file deny rules

### Refactoring
- Extracted constants, CommandHandler, and config inheritance into separate modules
- Fixed `_to_bool` parsing and feature envy in agent configuration

## 2026-03-02

### Features
- **Codegen server** — Experimental MCP server for structured code generation tasks
- **`run_task` tool** — Execute codegen tasks with inline prompts
- **Ctrl+C interrupts** — Ctrl+C now interrupts the current agent turn instead of killing the process
- **Per-call cost breakdown** — `/cost` command shows per-API-call breakdown
- **Prompt caching in codegen** — Cache metrics propagated from nested LLM calls

### Fixes
- Fixed JobServe email parser and structuredContent text fallback
- Replaced hand-rolled HTML-to-text with `html-to-text` library
- Fixed pricing lookup for model names without date suffix
- Nested LLM costs from MCP tools now tracked in `/cost` metrics

### Docs
- Added cache-preserving tool routing design and plan
- Added research on KV cache mechanics and MCP tool routing

## 2026-03-01 and Earlier

### Features
- **Cost reduction architecture** (ADR-012) — Prompt caching, conversation compaction, tool result summarization, mode analysis, concise output mode
- **Mode analysis** — Two-stage prompt classification (pattern matching + LLM) to detect compiled-mode tasks
- **Multi-provider LLM support** (ADR-010) — Pluggable provider abstraction supporting Anthropic and OpenAI
- **Session persistence** (ADR-009) — SQLite-backed session memory with checkpoint rewind
- **Continuous voice mode** (ADR-011) — STT via MCP sessions with `/voice` orchestration
- **Web tools** — `web_fetch` for content extraction, `web_search` via Brave Search API
- **Google integration** — Gmail (search, read, send), Calendar (list, create, get events), Contacts
- **WhatsApp integration** — Contact search, chat history, message sending, media transfer
- **GitHub tools** — PRs, issues, code search, file access via MCP
- **Anthropic usage** — Admin API cost reporting via `anthropic_usage` tool
- **Conversation compaction** — Strategy pattern with summarize compaction to manage context length
- **Configurable logging** — Loguru-based logging with tool execution spinner
- **Structured metrics** — JSON Lines metrics emission for cost tracking and analysis

### Architecture
- MCP for all external tools (ADR-005)
- Separate repos for third-party MCP servers (ADR-006)
- Streaming responses via SSE (ADR-003)
- python-dotenv for secrets (ADR-001)
- tenacity for retry logic (ADR-002)
- Raw HTML for Gmail (ADR-004)
- Google Contacts as built-in tools (ADR-007)
- GitHub tools via raw httpx (ADR-008)

### Initial Release
- Python port of micro-x-agent-loop with interactive REPL
- Tool protocol with name, description, execute, is_mutating
- Bash, read_file, write_file, append_file built-in tools
- One-command startup via run.bat / run.sh
