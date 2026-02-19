# Software Architecture Document

**Project:** micro-x-agent-loop-python
**Version:** 1.0
**Last Updated:** 2026-02-19

## 1. Introduction and Goals

micro-x-agent-loop-python is a minimal AI agent loop built with Python and the Anthropic Claude API. It provides a REPL interface where users type natural-language prompts and the agent autonomously calls tools to accomplish tasks.

### Key Goals

- Provide a simple, extensible agent loop for personal automation
- Support file operations, shell commands, job searching, and email
- Stream responses in real time for better user experience
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
| Anthropic Claude API | LLM provider for reasoning and tool dispatch |
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
    Agent --> LinkedIn[LinkedIn Web]
    Agent --> Gmail[Gmail API]
    Agent --> MCP[MCP Servers]
    Agent --> WhatsApp[WhatsApp Web<br/>via MCP + Bridge]
```

The agent sits between the user and external services. The user provides natural-language instructions; the agent uses Claude to decide which tools to call, executes them, and returns results.

### External Interfaces

| Interface | Protocol | Purpose |
|-----------|----------|---------|
| Anthropic API | HTTPS / SSE | LLM reasoning and tool dispatch |
| Gmail API | HTTPS / OAuth2 | Email search, read, send |
| LinkedIn | HTTPS / HTML scraping | Job search and detail fetching |
| Local shell | Process execution | Bash/cmd commands |
| File system | Direct I/O | Read/write files (.txt, .docx) |
| MCP servers | stdio / StreamableHTTP | Dynamic external tools via Model Context Protocol |
| WhatsApp Web | MCP stdio + HTTP :8080 + WebSocket | Messaging via Go bridge (whatsmeow) and Python MCP server |

## 4. Solution Strategy

| Decision | Approach |
|----------|----------|
| Agent loop | Iterative: send message, check for tool_use, execute tools, repeat |
| Streaming | `client.messages.stream()` prints text deltas in real time |
| Resilience | tenacity decorator with exponential backoff for rate limits |
| Secrets | `.env` file loaded by python-dotenv; never committed to git |
| App config | `config.json` for non-secret settings |
| Tool extensibility | `Tool` Protocol class; register in `tool_registry` or connect via MCP |
| Shared MCP server | [mcp-servers](https://github.com/StephenDenisEdwards/mcp-servers) repo — .NET MCP server providing system information tools (shared with .NET agent) |

## 5. Building Block View

### Level 1: Components

```mermaid
graph TD
    Main["__main__.py<br/>Entry Point"] --> Agent["Agent<br/>Loop Orchestrator"]
    Main --> Config["Configuration<br/>config.json + .env"]
    Main --> Registry["tool_registry<br/>Tool Factory"]
    Main --> McpMgr["McpManager<br/>MCP Connections"]

    Agent --> LlmClient["llm_client<br/>API + Streaming"]
    Agent --> Tools["Tool Implementations"]
    Agent --> McpTools["MCP Tool Proxies"]

    LlmClient --> Tenacity["tenacity<br/>Retry on 429"]
    LlmClient --> Anthropic["anthropic SDK"]

    McpMgr --> McpSDK["mcp SDK"]
    McpMgr --> McpTools

    subgraph Tools
        direction TB
        Bash[BashTool]
        ReadFile[ReadFileTool]
        WriteFile[WriteFileTool]
        LI1[LinkedInJobsTool]
        LI2[LinkedInJobDetailTool]
        Gmail1[GmailSearchTool]
        Gmail2[GmailReadTool]
        Gmail3[GmailSendTool]
    end

    subgraph McpTools["MCP Tool Proxies"]
        direction TB
        McpProxy1["McpToolProxy<br/>(per discovered tool)"]
    end
```

### Level 2: Key Modules

| Module | Responsibility |
|--------|---------------|
| `__main__` | Entry point; loads config, builds tools, initializes MCP, runs REPL |
| `Agent` | Manages conversation history, dispatches tool calls in parallel, enforces limits |
| `AgentConfig` | Dataclass holding all agent configuration with defaults |
| `llm_client` | Wraps Anthropic SDK; streaming + tenacity retry |
| `tool_registry` | Factory that assembles the built-in tool list with dependencies |
| `Tool` | Protocol class: `name`, `description`, `input_schema`, `execute` |
| `McpManager` | Connects to all configured MCP servers, discovers tools, manages lifecycle |
| `McpToolProxy` | Adapter wrapping an MCP tool + session into the `Tool` Protocol |
| [mcp-servers](https://github.com/StephenDenisEdwards/mcp-servers) (external) | Shared .NET MCP server exposing `system_info`, `disk_info`, `network_info` via stdio |
| WhatsApp MCP (external) | External two-component MCP server: Go bridge (WhatsApp Web connection, SQLite, HTTP API) + Python FastMCP server (12 tools for messaging, contacts, chats) |
| `html_utilities` | Shared HTML-to-plain-text conversion |
| `gmail_auth` | OAuth2 flow and token caching for Gmail |
| `gmail_parser` | Base64url decoding, MIME parsing, text extraction |

## 6. Runtime View

### Agent Loop Sequence

```mermaid
sequenceDiagram
    participant U as User
    participant M as __main__
    participant A as Agent
    participant L as llm_client
    participant C as Claude API
    participant T as Tools

    U->>M: Input prompt
    M->>A: run(prompt)
    A->>L: stream_chat(messages)
    L->>C: client.messages.stream()
    C-->>L: Text deltas (SSE)
    L-->>U: Print text in real time
    C-->>L: tool_use blocks
    L-->>A: (message, tool_use_blocks)

    loop For each tool (parallel via asyncio.gather)
        A->>T: execute(input)
        T-->>A: result (truncated if > limit)
    end

    A->>L: stream_chat(messages + tool results)
    L->>C: client.messages.stream()
    C-->>L: Final text response
    L-->>U: Print text in real time
    A-->>M: Return
```

### Conversation History Management

When the message list exceeds `MaxConversationMessages`, the oldest messages are removed and a warning is printed to stderr.

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
- Unrecoverable errors propagate to the REPL catch block

### Security

- API keys stored in `.env`, loaded at startup, never logged
- `.env` is in `.gitignore`
- Gmail tokens stored in `.gmail-tokens/` (also gitignored)
- BashTool executes arbitrary commands (by design for agent autonomy)

### Configuration Layers

| Layer | Source | Purpose |
|-------|--------|---------|
| Secrets | `.env` | API keys (Anthropic, Google) |
| App settings | `config.json` | Model, tokens, temperature, limits, paths |
| Defaults | Code | Fallback values when config is missing |

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

## 9. Risks and Technical Debt

| Risk | Impact | Mitigation |
|------|--------|-----------|
| LinkedIn HTML scraping is brittle | Job tools break when LinkedIn changes DOM | Multiple CSS selector fallbacks; accept degradation |
| No unit tests | Regressions go undetected | Future: add pytest test suite |
| Single Gmail account | Can't switch users without restart | Acceptable for personal use |
| BashTool has no sandboxing | Agent can execute any command | By design; user accepts risk |

## 10. Glossary

| Term | Definition |
|------|-----------|
| Agent loop | Iterative cycle: prompt -> LLM -> tool calls -> LLM -> response |
| Tool use | Claude's mechanism for requesting function execution |
| SSE | Server-Sent Events; used for streaming API responses |
| Rate limit | API throttling (HTTP 429); handled by tenacity retry |
| REPL | Read-Eval-Print Loop; the interactive console interface |
| Protocol | Python structural typing — any class with matching methods satisfies the interface |
