# Changelog

All notable changes to micro-x-agent-loop-python are documented here, grouped by feature area.

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
