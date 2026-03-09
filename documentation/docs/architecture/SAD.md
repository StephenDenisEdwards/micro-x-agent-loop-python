# Software Architecture Document

**Project:** micro-x-agent-loop-python
**Version:** 3.1
**Last Updated:** 2026-03-09

## 1. Introduction and Goals

Micro-X Agent is a general-purpose, cost-aware AI agent built with Python and a pluggable LLM backend (Anthropic Claude or OpenAI GPT). It provides a REPL interface where users type natural-language prompts (or use voice mode) and the agent autonomously orchestrates tools via the Model Context Protocol (MCP) to accomplish tasks.

### Key Goals

- Provide a simple, extensible agent loop for personal automation
- Support file operations, shell commands, web search, job searching, email, GitHub, and messaging
- Stream responses in real time for better user experience
- Persist session state and execution history for continuity across restarts
- Enable human-in-the-loop questioning so the LLM can ask clarifying questions mid-execution
- Support cost-aware execution via mode selection (prompt vs compiled) and layered cost reduction
- Keep the codebase small and easy to understand

### Stakeholders

| Role | Concern |
|------|---------|
| User | Natural-language task completion via tools |
| Developer | Easy to add new tools, understand the codebase |

## 2. Constraints

| Constraint | Rationale |
|-----------|-----------|
| Python 3.11+ | Minimum version for `typing.Protocol` features and modern syntax |
| Anthropic or OpenAI API | LLM provider for reasoning and tool dispatch (config-driven) |
| Console application | Simplicity; no web UI overhead |
| OAuth2 for Gmail | Required by Google API |

## 3. Context and Scope

### System Context

```mermaid
graph LR
    User([User]) --> Agent[micro-x-agent-loop]
    Agent --> Claude[Anthropic Claude API]
    Agent --> Shell[Local Shell]
    Agent --> FS[File System]
    Agent --> SQLite[SQLite Memory DB]
    Agent --> LinkedIn[LinkedIn Web]
    Agent --> Gmail[Gmail API]
    Agent --> GitHub[GitHub API]
    Agent --> BraveSearch[Brave Search API]
    Agent --> MCP[MCP Servers]
    Agent --> WhatsApp[WhatsApp Web<br/>via MCP + Bridge]
```

The agent sits between the user and external services. The user provides natural-language instructions; the agent uses the configured LLM to decide which tools to call, executes them, and returns results. Session state is persisted locally in SQLite when memory is enabled.

### External Interfaces

| Interface | Protocol | Purpose |
|-----------|----------|---------|
| Anthropic API | HTTPS / SSE | LLM reasoning and tool dispatch (default provider) |
| OpenAI API | HTTPS / SSE | LLM reasoning and tool dispatch (alternative provider) |
| Gmail API | HTTPS / OAuth2 | Email search, read, send |
| Google Contacts API | HTTPS / OAuth2 | Contact search, create, update, delete |
| Google Calendar API | HTTPS / OAuth2 | Event listing, creation, retrieval |
| GitHub API | HTTPS (Octokit) | Repos, PRs, issues, code search, file access |
| Brave Search API | HTTPS | Web search results |
| LinkedIn | HTTPS / HTML scraping | Job search and detail fetching |
| Local shell | Process execution | Bash/cmd commands |
| File system | Direct I/O | Read/write files (.txt, .docx) |
| SQLite | Local file I/O | Session, message, checkpoint, and event persistence |
| MCP servers | stdio / StreamableHTTP | Dynamic external tools via Model Context Protocol |
| Deepgram STT (via Interview Assist MCP) | HTTPS / WebSocket | Continuous speech transcription for voice mode |
| WhatsApp Web | MCP stdio + HTTP :8080 + WebSocket | Messaging via Go bridge (whatsmeow) and Python MCP server |

## 4. Solution Strategy

| Decision | Approach |
|----------|----------|
| Agent loop | Iterative: send message, check for tool_use, execute tools, repeat |
| Multi-provider | `LLMProvider` Protocol with Anthropic-format canonical messages; translation at API boundary |
| Streaming | Provider-specific streaming (Anthropic SSE / OpenAI SSE) prints text deltas in real time |
| Resilience | tenacity decorator with exponential backoff for rate limits (per-provider); `resilientFetch` in TypeScript MCP servers for HTTP retry ([ADR-016](decisions/ADR-016-retry-resilience-for-mcp-servers-and-transport.md)) |
| Secrets | `.env` file loaded by python-dotenv; never committed to git |
| App config | `config.json` for non-secret settings |
| Tool extensibility | `Tool` Protocol class; all tools are TypeScript MCP servers discovered at startup ([ADR-015](decisions/ADR-015-all-tools-as-typescript-mcp-servers.md)) |
| Session persistence | Opt-in SQLite-backed memory for sessions, messages, tool calls, checkpoints, and events |
| File safety | Checkpoint/rewind for mutating tools (`write_file`, `append_file`) |
| Human-in-the-loop | `ask_user` pseudo-tool for LLM-initiated clarifying questions ([ADR-017](decisions/ADR-017-ask-user-pseudo-tool-for-human-in-the-loop.md)) |
| Cost reduction | Layered approach: prompt caching, tool schema caching, compaction, concise output, tool search ([ADR-012](decisions/ADR-012-layered-cost-reduction.md)) |
| Mode selection | Structural pattern matching + optional LLM classification to route prompts to compiled or prompt mode |
| Shared MCP server | [mcp-servers](https://github.com/StephenDenisEdwards/mcp-servers) repo — .NET MCP server providing system information tools |

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| [anthropic](https://pypi.org/project/anthropic/) | >=0.42.0 | Anthropic Claude API (official SDK) |
| [openai](https://pypi.org/project/openai/) | >=1.0.0 | OpenAI API (official SDK) |
| [tenacity](https://pypi.org/project/tenacity/) | >=9.0.0 | Retry with exponential backoff |
| [python-dotenv](https://pypi.org/project/python-dotenv/) | >=1.0.0 | Load `.env` files |
| [mcp](https://pypi.org/project/mcp/) | >=1.0.0 | Model Context Protocol client |
| [loguru](https://pypi.org/project/loguru/) | >=0.7.0 | Structured logging |
| [tiktoken](https://pypi.org/project/tiktoken/) | >=0.7.0 | Token counting for tool search threshold |
| [questionary](https://pypi.org/project/questionary/) | >=2.0.0 | Interactive terminal prompts for ask_user |
| [croniter](https://pypi.org/project/croniter/) | >=1.3.0 | Cron expression parsing for trigger broker |
| [httpx](https://pypi.org/project/httpx/) | >=0.27.0 | Async HTTP client |
| [google-api-python-client](https://pypi.org/project/google-api-python-client/) | >=2.150.0 | Google APIs (Gmail, Calendar, Contacts) |
| [google-auth-oauthlib](https://pypi.org/project/google-auth-oauthlib/) | >=1.2.0 | Google OAuth2 authentication |
| [python-docx](https://pypi.org/project/python-docx/) | >=1.1.0 | DOCX file reading |
| [beautifulsoup4](https://pypi.org/project/beautifulsoup4/) | >=4.12.0 | HTML parsing |
| [lxml](https://pypi.org/project/lxml/) | >=5.0.0 | XML/HTML parser backend |

## 5. Building Block View

### Level 1: Components

```mermaid
graph TD
    Main["__main__.py<br/>Entry Point"] --> Bootstrap["bootstrap.py<br/>Runtime Factory"]
    Main --> Broker["broker/<br/>Trigger Broker"]
    Bootstrap --> Agent["Agent<br/>Orchestrator"]
    Bootstrap --> Config["app_config.py<br/>config.json + .env"]
    Bootstrap --> McpMgr["McpManager<br/>MCP Connections"]
    Bootstrap --> Memory["memory/<br/>SQLite Persistence"]

    Broker --> BrokerStore["BrokerStore<br/>Jobs + Runs DB"]
    Broker --> Scheduler["Scheduler<br/>Cron Polling"]
    Scheduler --> Runner["Runner<br/>Subprocess Dispatch"]
    Runner --> Main

    Agent --> TurnEngine["TurnEngine<br/>LLM Turn Loop"]
    Agent --> CmdRouter["CommandRouter<br/>Local Commands"]
    Agent --> VoiceRT["VoiceRuntime<br/>STT Integration"]
    Agent --> Formatter["ToolResultFormatter<br/>Structured → Text"]
    Agent --> AskUser["AskUserHandler<br/>Human-in-the-Loop"]
    Agent --> ToolSearch["ToolSearchManager<br/>On-Demand Discovery"]
    Agent --> SubAgent["SubAgentRunner<br/>Delegated Tasks"]
    Agent --> ModeSelect["ModeSelector<br/>Prompt vs Compiled"]

    TurnEngine --> Provider["LLMProvider<br/>Protocol"]
    TurnEngine --> McpTools["MCP Tool Proxies"]
    TurnEngine --> Events["TurnEvents<br/>Lifecycle Callbacks"]
    TurnEngine --> Constants["constants.py<br/>Shared Defaults"]

    Agent --> Memory

    Provider --> AnthropicProv["AnthropicProvider"]
    Provider --> OpenAIProv["OpenAIProvider"]
    AnthropicProv --> Anthropic["anthropic SDK"]
    OpenAIProv --> OpenAISDK["openai SDK"]
    AnthropicProv --> Tenacity["tenacity<br/>Retry on 429"]
    OpenAIProv --> Tenacity

    McpMgr --> McpSDK["mcp SDK"]
    McpMgr --> McpTools

    subgraph Memory["memory/ (SQLite)"]
        direction TB
        Store["MemoryStore"]
        SessionMgr["SessionManager"]
        CheckpointMgr["CheckpointManager"]
        EventEmitter["EventEmitter"]
        EventSink["EventSink"]
        Facade["MemoryFacade"]
        Pruning["prune_memory"]
    end

    subgraph McpServers["MCP Servers"]
        direction TB
        FS["filesystem<br/>bash, read_file, write_file,<br/>append_file, save_memory"]
        Web["web<br/>web_fetch, web_search"]
        LI["linkedin<br/>linkedin_jobs, linkedin_job_detail,<br/>draft_post, draft_article, publish_draft"]
        XT["x-twitter<br/>7 tools (draft/publish/analytics)"]
        GH["github<br/>8 tools"]
        Google["google<br/>12 tools"]
        Admin["anthropic-admin<br/>anthropic_usage"]
        IA["interview-assist<br/>14 tools"]
        Codegen["codegen (Python)<br/>generate_code"]
    end

    McpMgr --> McpServers

    subgraph McpTools["MCP Tool Proxies"]
        direction TB
        McpProxy1["McpToolProxy<br/>(per discovered tool)"]
    end
```

### Level 2: Key Modules

| Module | Responsibility |
|--------|---------------|
| `__main__` | Entry point; loads config, displays startup logo, delegates to bootstrap, runs REPL |
| `bootstrap` | Factory that wires all runtime components (MCP tools, providers, memory) into an `AppRuntime` |
| `app_config` | Parses `config.json` into `AppConfig` dataclass; resolves runtime environment variables into `RuntimeEnv` |
| `Agent` | Top-level orchestrator: holds conversation state, routes commands, delegates turns to `TurnEngine` |
| `AgentConfig` | Dataclass holding all agent configuration (model, tools, memory components, compaction) |
| `TurnEngine` | Executes a single LLM turn: streams response, classifies tool blocks (search/ask_user/subagent/regular), dispatches tools in parallel, handles retries |
| `SubAgentRunner` | Creates lightweight, disposable in-process agent instances for focused tasks. Three types: explore (read-only, cheap), summarize (no tools), general (full capability). Results return as tool_result to parent. |
| `TurnEvents` | Protocol defining lifecycle callbacks: `on_append_message`, `on_api_call_completed`, `on_tool_executed`, `on_ensure_checkpoint_for_turn`, etc. `BaseTurnEvents` provides no-op defaults. |
| `AskUserHandler` | Pseudo-tool handler for human-in-the-loop questioning. Presents structured choices via `questionary` with "Other" free-text escape; falls back to plain `input()` for non-interactive terminals. |
| `ToolSearchManager` | On-demand tool discovery pseudo-tool. Replaces large schema payloads with a single search tool when schema size exceeds a threshold. Uses `tiktoken` for token counting. |
| `ModeSelector` | Stage 1 structural pattern matching + Stage 2 LLM classification for routing prompts to compiled vs prompt mode. Pure computation, no async. |
| `ToolResultFormatter` | Formats `ToolResult.structured` into LLM-friendly text using per-tool config (json, table, text, key_value strategies) |
| `CommandRouter` | Routes `/help`, `/session`, `/checkpoint`, `/voice` commands to handlers |
| `SessionController` | Formatting service for session list entries, summaries, and short IDs |
| `broker/service` | Always-on daemon lifecycle: PID file, signal handling, graceful shutdown |
| `broker/scheduler` | Cron polling loop: checks due jobs, enforces overlap policy, dispatches runs via subprocess |
| `broker/store` | SQLite persistence for broker jobs and run history (`broker_jobs`, `broker_runs` tables) |
| `broker/runner` | Subprocess dispatcher: spawns `--run` agent processes in autonomous mode |
| `broker/cli` | CLI commands for `--broker` and `--job` management |
| `CheckpointService` | Formatting service for checkpoint list entries and rewind outcome reports |
| `VoiceRuntime` | Manages continuous voice input via MCP STT sessions (start/stop/poll) |
| `VoiceIngress` | Protocol for streaming STT events; `PollingVoiceIngress` polls MCP for updates |
| `LLMProvider` | Protocol defining `stream_chat`, `create_message`, `convert_tools` |
| `AnthropicProvider` | Anthropic SDK implementation of `LLMProvider` |
| `OpenAIProvider` | OpenAI SDK implementation of `LLMProvider` (translates message format at API boundary) |
| `llm_client` | Shared utilities: `Spinner` (terminal feedback), `_on_retry` (tenacity callback) |
| `constants` | Centralised magic numbers and defaults (token limits, compaction thresholds, tool search config). All modules import from here. |
| `metrics` | Structured metrics emission via loguru for cost tracking, API call analysis, and tool execution timing |
| `usage` | `UsageResult` dataclass (input/output tokens, cache hits, duration) and pricing lookup for cost estimation |
| `api_payload_store` | In-memory ring buffer for API request/response payloads (debugging) |
| `analyze_costs` | CLI module for analysing `metrics.jsonl` files: per-session breakdown, comparisons, CSV export |
| `logging_config` | `LogConsumer` Protocol with `ConsoleLogConsumer` and `FileLogConsumer` implementations for loguru setup |
| `Tool` | Protocol class: `name`, `description`, `input_schema`, `is_mutating`, `predict_touched_paths`, `execute` |
| `ToolResult` | Dataclass: `text`, `structured` (dict or None), `is_error` — returned by `Tool.execute()` |
| `system_prompt` | System prompt text with conditional directives for tool search, ask_user, and sub-agent delegation |
| `compaction` | Conversation compaction strategies: `NoOpCompaction` and `SummarizeCompaction` (LLM-based) |
| `memory/store` | SQLite connection, schema bootstrap (6 tables), transaction context manager |
| `memory/session_manager` | Session CRUD, message persistence with monotonic sequencing, fork, tool call recording |
| `memory/checkpoints` | File snapshotting before mutations, rewind with per-file outcome reporting |
| `memory/events` | Synchronous event emission to DB |
| `memory/event_sink` | Async batched event emission (queue + periodic flush) |
| `memory/facade` | `MemoryFacade` Protocol with `ActiveMemoryFacade` (real) and `NullMemoryFacade` (no-op) — callers never need null-check guards |
| `memory/pruning` | Time-based and count-based retention enforcement |
| `memory/models` | Frozen dataclasses for `SessionRecord` and `MessageRecord` |
| `McpManager` | Connects to all configured MCP servers in parallel, discovers tools, manages lifecycle |
| `McpToolProxy` | Adapter wrapping an MCP tool + session into the `Tool` Protocol; extracts `structuredContent` into `ToolResult.structured` |
| `mcp_servers/ts/` | TypeScript npm workspaces monorepo containing 8 first-party MCP servers (filesystem, web, linkedin, x-twitter, github, google, anthropic-admin, interview-assist) plus shared utilities |
| `mcp_servers/python/codegen/` | Python FastMCP server exposing `generate_code` — isolated single-shot code generation via Anthropic API with zero tools (see [DESIGN-codegen-server](../design/DESIGN-codegen-server.md)) |
| [mcp-servers](https://github.com/StephenDenisEdwards/mcp-servers) (external) | .NET MCP server exposing `system_info`, `disk_info`, `network_info` via stdio |
| WhatsApp MCP (external) | External two-component MCP server: Go bridge (WhatsApp Web connection, SQLite, HTTP API) + Python FastMCP server (12 tools for messaging, contacts, chats) |

## 6. Runtime View

### Agent Loop Sequence

```mermaid
sequenceDiagram
    participant U as User
    participant M as __main__
    participant A as Agent
    participant TE as TurnEngine
    participant P as LLMProvider
    participant API as LLM API
    participant T as Tools
    participant Mem as Memory (SQLite)

    M->>A: initialize_session()
    A->>Mem: load_messages(session_id)
    Mem-->>A: Persisted messages

    U->>M: Input prompt
    M->>A: run(prompt)
    A->>TE: run(messages, user_message)
    TE->>Mem: append_message(user)
    TE->>P: stream_chat(messages)
    P->>API: Provider-specific streaming call
    API-->>P: Text deltas (SSE)
    P-->>U: Print text in real time
    API-->>P: tool_use / tool_calls
    P-->>TE: (message, tool_use_blocks, stop_reason)
    TE->>Mem: append_message(assistant)

    Note over TE: Classify blocks: search / ask_user / subagent / regular

    alt tool_search blocks
        TE->>TE: ToolSearchManager.handle_tool_search(query)
        Note over TE: Load matching tool schemas inline
    end

    alt ask_user blocks
        TE->>U: AskUserHandler.handle() — display question + options
        U-->>TE: User selects option or types answer
        Note over TE: Return {"answer": "..."} as tool_result
    end

    alt subagent blocks
        TE->>TE: SubAgentRunner.run(task, type)
        Note over TE: Fresh TurnEngine with filtered tools,<br/>cheap model, disposable context
        Note over TE: Return summary as tool_result
    end

    alt No regular tools (pseudo-tools only)
        TE->>Mem: append inline_results
        Note over TE: Continue to next LLM call
    end

    alt Regular tool blocks
        TE->>Mem: create_checkpoint(turn)
        loop For each tool (parallel via asyncio.gather)
            TE->>Mem: snapshot file (pre-mutation)
            TE->>T: execute(input)
            T-->>TE: result (truncated if > limit)
            TE->>Mem: record_tool_call()
        end
        Note over TE: Merge inline_results + tool_results in original order
    end

    TE->>P: stream_chat(messages + tool results)
    P->>API: Provider-specific streaming call
    API-->>P: Final text response
    P-->>U: Print text in real time
    TE-->>A: Return
```

### Conversation History Management

Before each LLM call, the agent runs its configured compaction strategy. With the `"summarize"` strategy, the middle of the conversation is summarized via an LLM call when estimated tokens exceed a threshold. After compaction, `_trim_conversation_history()` runs as a hard backstop — when `len(_messages)` exceeds `MaxConversationMessages`, the oldest messages are removed. See [Compaction Design](../design/DESIGN-compaction.md).

### Tool Result Truncation

When a tool result exceeds `MaxToolResultChars`, it is truncated and a message is appended:
```
[OUTPUT TRUNCATED: Showing 40,000 of 85,000 characters from read_file]
```
A warning is also printed to stderr.

## 7. Crosscutting Concepts

### Error Handling

- Tool execution errors are caught and returned as error text to Claude (not raised)
- Unknown tool names return an error result
- API rate limits are retried automatically via tenacity
- HTTP errors in TypeScript MCP servers are retried via `resilientFetch` / Octokit plugins ([ADR-016](decisions/ADR-016-retry-resilience-for-mcp-servers-and-transport.md))
- MCP transport errors (stdio pipe breaks) are retried via tenacity in `McpClient.call_tool()`
- Checkpoint tracking failures are non-blocking (logged + event emitted, tool still executes)
- Unrecoverable errors propagate to the REPL catch block

### Session Persistence and Memory

When `MemoryEnabled=true`, the agent persists all conversation state to a local SQLite database:

- **Sessions** — create, resume, fork, rename, list. Session resolution supports ID or case-insensitive title match.
- **Messages** — every user/assistant message is persisted with monotonic sequencing. On resume, messages are reloaded into the in-memory conversation.
- **Tool calls** — full input/output/error records for each tool invocation.
- **Checkpoints** — file snapshots before mutating tools execute. `/rewind` restores files to checkpoint state.
- **Events** — structured lifecycle events (session, message, tool, checkpoint, rewind) persisted for traceability.
- **Pruning** — time-based and count-based retention runs at startup.

See [Memory System Design](../design/DESIGN-memory-system.md) and [ADR-009](decisions/ADR-009-sqlite-memory-sessions-and-file-checkpoints.md).

### Security

- API keys stored in `.env`, loaded at startup, never logged
- `.env` is in `.gitignore`
- Service-specific credentials (Google, Brave, GitHub, Anthropic Admin) flow to MCP servers via `env` blocks in `McpServers` config
- The `bash` tool executes arbitrary commands (by design for agent autonomy)
- Checkpoint file backups are stored in the local SQLite database

### Configuration Layers

| Layer | Source | Purpose |
|-------|--------|---------|
| Secrets | `.env` | LLM provider API key (Anthropic or OpenAI) |
| MCP server env | `config.json` `McpServers.*.env` | Per-server credentials (Google, Brave, GitHub, etc.) |
| App settings | `config.json` | Model, tokens, temperature, limits, paths, memory, MCP servers |
| Defaults | Code (`constants.py`) | Fallback values when config is missing |

See [Configuration Reference](../operations/config.md) for the full settings table.

## 8. Architecture Decisions

See [Architecture Decision Records](decisions/README.md) for the full index.

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-001](decisions/ADR-001-python-dotenv-for-secrets.md) | python-dotenv for secrets management | Accepted |
| [ADR-002](decisions/ADR-002-tenacity-for-retry.md) | tenacity for API retry resilience | Accepted |
| [ADR-003](decisions/ADR-003-streaming-responses.md) | Streaming responses via SSE | Accepted |
| [ADR-004](decisions/ADR-004-raw-html-for-gmail.md) | Raw HTML for Gmail email content | Accepted |
| [ADR-005](decisions/ADR-005-mcp-for-external-tools.md) | MCP for external tool integration | Accepted |
| [ADR-006](decisions/ADR-006-separate-repos-for-third-party-mcp-servers.md) | Separate repos for third-party MCP servers | Accepted |
| [ADR-007](decisions/ADR-007-google-contacts-built-in-tools.md) | Google Contacts as built-in tools | Accepted |
| [ADR-008](decisions/ADR-008-github-built-in-tools-with-raw-httpx.md) | GitHub as built-in tools via raw httpx | Accepted |
| [ADR-009](decisions/ADR-009-sqlite-memory-sessions-and-file-checkpoints.md) | SQLite memory for sessions, events, and file checkpoints | Accepted |
| [ADR-010](decisions/ADR-010-multi-provider-llm-support.md) | Multi-provider LLM support (provider abstraction) | Accepted |
| [ADR-011](decisions/ADR-011-continuous-voice-mode-via-stt-mcp-sessions.md) | Continuous voice mode via STT MCP sessions | Accepted |
| [ADR-012](decisions/ADR-012-layered-cost-reduction.md) | Layered cost reduction architecture | Accepted |
| [ADR-013](decisions/ADR-013-tool-result-summarization-reliability.md) | Tool result summarization is fundamentally unreliable | Accepted |
| [ADR-014](decisions/ADR-014-mcp-unstructured-data-constraint.md) | Tool results are unstructured text — design choice affecting compiled mode | Open |
| [ADR-015](decisions/ADR-015-all-tools-as-typescript-mcp-servers.md) | All tools as TypeScript MCP servers | Accepted |
| [ADR-016](decisions/ADR-016-retry-resilience-for-mcp-servers-and-transport.md) | Retry/resilience for MCP servers and transport | Accepted |
| [ADR-017](decisions/ADR-017-ask-user-pseudo-tool-for-human-in-the-loop.md) | Ask user pseudo-tool for human-in-the-loop questioning | Accepted |
| [ADR-018](decisions/ADR-018-trigger-broker-subprocess-dispatch.md) | Trigger broker with subprocess dispatch | Accepted |

## 9. Risks and Technical Debt

| Risk | Impact | Mitigation |
|------|--------|-----------|
| LinkedIn HTML scraping is brittle | Job tools break when LinkedIn changes DOM | Multiple CSS selector fallbacks; accept degradation |
| Single Gmail account | Can't switch users without restart | Acceptable for personal use |
| BashTool has no sandboxing | Agent can execute any command | By design; user accepts risk |
| Bash mutations are not tracked by checkpoints | `/rewind` cannot restore files changed by shell commands | Phase 3 planned: best-effort command parsing for mutation detection |
| SQLite memory growth | Long-running usage accumulates data | Configurable retention policies with pruning at startup |

## 10. Glossary

| Term | Definition |
|------|-----------|
| Agent loop | Iterative cycle: prompt -> LLM -> tool calls -> LLM -> response |
| Tool use | Claude's mechanism for requesting function execution |
| SSE | Server-Sent Events; used for streaming API responses |
| Rate limit | API throttling (HTTP 429); handled by tenacity retry |
| REPL | Read-Eval-Print Loop; the interactive console interface |
| Protocol | Python structural typing — any class with matching methods satisfies the interface |
| Session | A persisted conversation timeline with a stable ID |
| Checkpoint | A snapshot of file state before mutating tools execute within a user turn |
| Rewind | Restoring files to their state at a given checkpoint |
| MCP | Model Context Protocol; standard for connecting LLM agents to external tool servers |
| Pseudo-tool | A tool handled inline by the agent (not via MCP execution) — e.g. `tool_search`, `ask_user`, `spawn_subagent` |
| Sub-agent | A lightweight, disposable in-process agent instance that runs a focused task in its own context window and returns a summary |
| Compiled mode | Cost-aware execution mode that generates code for batch-processing tasks instead of running them conversationally |
