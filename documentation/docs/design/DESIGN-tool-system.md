# Design: Tool System

## Overview

The tool system provides Claude with the ability to interact with the outside world. Each tool is a self-contained unit that accepts a dict input, performs an action, and returns a string result.

## Tool Protocol

```python
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class Tool(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def input_schema(self) -> dict[str, Any]: ...

    @property
    def is_mutating(self) -> bool: ...

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]: ...

    async def execute(self, tool_input: dict[str, Any]) -> str: ...
```

| Member | Purpose |
|--------|---------|
| `name` | Unique identifier sent to Claude (e.g., `"read_file"`) |
| `description` | Natural-language description Claude uses to decide when to call the tool |
| `input_schema` | JSON Schema dict defining the expected input parameters |
| `is_mutating` | Whether the tool modifies files (used by checkpoint tracking) |
| `predict_touched_paths` | Returns predicted file paths the tool will modify (used for pre-mutation snapshots) |
| `execute` | Executes the tool and returns a string result |

Using `typing.Protocol` provides structural typing — any class with matching properties and methods satisfies the interface without explicit inheritance.

### Mutation Metadata

Tools that modify files should declare `is_mutating = True` and implement `predict_touched_paths()` to return the list of file paths they will modify. When file checkpointing is enabled, the agent uses this metadata to snapshot files before mutation so they can be restored via `/rewind`.

Currently three tools implement mutation metadata:

| Tool | Strategy | Notes |
|------|----------|-------|
| `write_file` | Strict | Returns `[path]` from tool input |
| `append_file` | Strict | Returns `[path]` from tool input |
| `bash` | Best-effort | Parses the shell command to extract likely mutated paths via `bash_command_parser.extract_mutated_paths()` |

Tools that don't modify files can return `False` and `[]` respectively, or omit these members entirely — the agent falls back to `getattr(tool, "is_mutating", False)` with a safe default.

By default (`CheckpointWriteToolsOnly=true`), only `write_file` and `append_file` are tracked. Set `CheckpointWriteToolsOnly=false` to also track bash mutations.

See [Memory System Design](DESIGN-memory-system.md) for the full checkpoint lifecycle and bash parser details.

## Tool Registry

`tool_registry.get_all()` assembles the tool list with their dependencies:

```python
def get_all(
    working_directory: str | None = None,
    google_client_id: str | None = None,
    google_client_secret: str | None = None,
    anthropic_admin_api_key: str | None = None,
    brave_api_key: str | None = None,
    github_token: str | None = None,
) -> list[Tool]:
```

Tool groups are conditionally registered based on available credentials. Gmail/Calendar and Contacts tools require both Google credentials. The Anthropic usage tool requires the admin API key. Web search requires the Brave API key. GitHub tools require a GitHub token. This prevents runtime errors when optional credentials are not configured.

## Built-in Tools

Each tool has its own detailed documentation in the [tools/](tools/) directory.

### File System

| Tool | Description | Mutating | Docs |
|------|-------------|----------|------|
| `read_file` | Read text files and `.docx` documents | No | [read-file](tools/read-file/README.md) |
| `write_file` | Write content to a file, creating directories as needed | Yes | [write-file](tools/write-file/README.md) |
| `append_file` | Append content to an existing file | Yes | — |

### Shell

| Tool | Description | Mutating | Docs |
|------|-------------|----------|------|
| `bash` | Execute a shell command (cmd.exe on Windows, bash on Unix) | Best-effort (opt-in) | [bash](tools/bash/README.md) |

### Web

| Tool | Description | Docs |
|------|-------------|------|
| `web_fetch` | Fetch and parse web content from a URL | — |
| `web_search` | Search the web via Brave Search API (conditional on `BRAVE_API_KEY`) | — |

### LinkedIn

| Tool | Description | Docs |
|------|-------------|------|
| `linkedin_jobs` | Search LinkedIn job postings with filters | [linkedin-jobs](tools/linkedin-jobs/README.md) |
| `linkedin_job_detail` | Fetch full job description from a LinkedIn URL | [linkedin-job-detail](tools/linkedin-job-detail/README.md) |

### Gmail (conditional)

| Tool | Description | Docs |
|------|-------------|------|
| `gmail_search` | Search Gmail using Gmail search syntax | [gmail-search](tools/gmail-search/README.md) |
| `gmail_read` | Read full email content by message ID | [gmail-read](tools/gmail-read/README.md) |
| `gmail_send` | Send a plain-text email | [gmail-send](tools/gmail-send/README.md) |

Gmail tools require OAuth2 authentication. On first use, a browser window opens for Google sign-in. Tokens are cached in `.gmail-tokens/`. See [ADR-004](../architecture/decisions/ADR-004-raw-html-for-gmail.md) for the decision to pass raw HTML to the LLM.

### Google Calendar (conditional)

| Tool | Description | Docs |
|------|-------------|------|
| `calendar_list_events` | List events by date range or search query | [calendar-list-events](tools/calendar-list-events/README.md) |
| `calendar_create_event` | Create events with title, time, attendees | [calendar-create-event](tools/calendar-create-event/README.md) |
| `calendar_get_event` | Get full event details by ID | [calendar-get-event](tools/calendar-get-event/README.md) |

Calendar tools use the same Google OAuth2 credentials as Gmail but with a separate token cache (`.calendar-tokens/`) and the `https://www.googleapis.com/auth/calendar` scope.

### Google Contacts (conditional)

| Tool | Description | Docs |
|------|-------------|------|
| `contacts_search` | Search contacts by name, email, or phone | — |
| `contacts_list` | List contacts with pagination | — |
| `contacts_get` | Get full contact details by resource name | — |
| `contacts_create` | Create a new contact | — |
| `contacts_update` | Update an existing contact | — |
| `contacts_delete` | Delete a contact | — |

Contacts tools share the same Google OAuth2 credentials as Gmail/Calendar with a separate token cache and the `https://www.googleapis.com/auth/contacts` scope. See [ADR-007](../architecture/decisions/ADR-007-google-contacts-built-in-tools.md).

### GitHub (conditional)

| Tool | Description | Docs |
|------|-------------|------|
| `github_list_repos` | List repositories for the authenticated user | — |
| `github_list_prs` | List pull requests for a repository | — |
| `github_get_pr` | Get full PR details | — |
| `github_create_pr` | Create a pull request | — |
| `github_list_issues` | List issues for a repository | — |
| `github_create_issue` | Create an issue | — |
| `github_get_file` | Get file contents from a repository | — |
| `github_search_code` | Search code across repositories | — |

Requires a GitHub personal access token (`GITHUB_TOKEN`). See [ADR-008](../architecture/decisions/ADR-008-github-built-in-tools-with-raw-httpx.md).

### Anthropic Admin (conditional)

| Tool | Description | Docs |
|------|-------------|------|
| `anthropic_usage` | Query usage, cost, and Claude Code productivity reports | [anthropic-usage](tools/anthropic-usage/README.md) |

Requires an Anthropic Admin API key (`sk-ant-admin...`), separate from the inference key. See [DESIGN-account-management-apis](DESIGN-account-management-apis.md) for full API surface details.

## MCP Tools (dynamic)

The agent supports dynamically discovering tools from external **MCP (Model Context Protocol)** servers. MCP tools are configured in `config.json` under `McpServers` — no code changes are needed to add new tool servers.

See [ADR-005](../architecture/decisions/ADR-005-mcp-for-external-tools.md) for the architectural decision.

### How It Works

1. At startup, `McpManager` reads the `McpServers` config and connects to each server
2. For each server, it calls `list_tools()` to discover available tools
3. Each discovered tool is wrapped in `McpToolProxy`, which adapts it to the `Tool` Protocol
4. MCP tools are merged with built-in tools and passed to the agent

The agent dispatches MCP tools identically to built-in tools — no special handling is needed.

### McpToolProxy

`McpToolProxy` is an adapter class in `mcp/mcp_tool_proxy.py` that wraps an MCP tool definition and session into a `Tool` Protocol object:

| Member | Behavior |
|--------|----------|
| `name` | `{server_name}__{tool_name}` — prefixed to avoid collisions with built-in tools |
| `description` | From the MCP tool's metadata |
| `input_schema` | From the MCP tool's `inputSchema` |
| `execute()` | Calls `session.call_tool(name, arguments)`, extracts text from result content blocks |

### McpManager

`McpManager` in `mcp/mcp_manager.py` manages the lifecycle of all MCP server connections. Each server runs in its own `asyncio.Task` with proper `async with` nesting (avoiding `AsyncExitStack`, which conflicts with anyio's cancel scopes used internally by `stdio_client`).

- `connect_all()` — starts each server in a background task, waits for it to be ready, returns discovered tools
- `close()` — shuts down each server individually with per-server logging and a 5-second timeout

Shutdown signals both the internal shutdown event and task cancellation together, ensuring both anyio and asyncio cleanup paths are triggered. On Windows, a `sys.unraisablehook` in `__main__.py` suppresses harmless "unclosed transport" noise from asyncio's proactor pipe cleanup.

Connection failures for individual servers are logged but do not prevent the agent from starting. Other servers and built-in tools continue to work normally.

### Supported Transports

| Transport | Config | Use Case |
|-----------|--------|----------|
| `stdio` | `command`, `args`, `env` | Local MCP servers spawned as child processes |
| `http` | `url` | Remote MCP servers via StreamableHTTP |

### Shared MCP Server: system-info

The system-info MCP server lives in the shared [mcp-servers](https://github.com/StephenDenisEdwards/mcp-servers) repository (used by both the Python and .NET agents). It demonstrates the stdio transport pattern and exposes three tools:

| MCP Tool | Agent Tool Name | Description |
|----------|----------------|-------------|
| `system_info` | `system-info__system_info` | OS, CPU, memory, uptime, .NET runtime |
| `disk_info` | `system-info__disk_info` | Per-drive disk usage (fixed drives) |
| `network_info` | `system-info__network_info` | Network interfaces with IP addresses |

Built with the [ModelContextProtocol](https://www.nuget.org/packages/ModelContextProtocol) NuGet package and `Microsoft.Extensions.Hosting`. Uses `Host.CreateEmptyApplicationBuilder(settings: null)` to avoid default logging to stdout (which would corrupt the stdio transport).

The server must be built before starting the agent (`dotnet build path/to/mcp-servers/system-info/src`). The config uses `--no-build` to skip the build step at runtime, and an absolute path to the server project.

### External MCP Server: WhatsApp

The agent can also connect to the [lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp) external MCP server for WhatsApp messaging. Unlike system-info, this server lives outside this repository and has a two-component architecture:

| Component | Role |
|-----------|------|
| Go bridge (`whatsapp-bridge/`) | Connects to WhatsApp Web via whatsmeow, stores messages in SQLite, exposes HTTP API on port 8080 |
| Python MCP server (`whatsapp-mcp-server/`) | FastMCP server that queries SQLite for messages and calls the bridge API for sending. Runs via `uv` as a stdio MCP server. |

The Go bridge must be running before the agent starts. The Python MCP server is spawned by McpManager as a child process.

| MCP Tool | Agent Tool Name | Description |
|----------|----------------|-------------|
| `search_contacts` | `whatsapp__search_contacts` | Search contacts by name or phone |
| `list_messages` | `whatsapp__list_messages` | Search/filter messages with pagination and context |
| `list_chats` | `whatsapp__list_chats` | List chats with search and sorting |
| `get_chat` | `whatsapp__get_chat` | Chat metadata by JID |
| `get_direct_chat_by_contact` | `whatsapp__get_direct_chat_by_contact` | Find direct chat by phone number |
| `get_contact_chats` | `whatsapp__get_contact_chats` | All chats involving a contact |
| `get_last_interaction` | `whatsapp__get_last_interaction` | Most recent message with a contact |
| `get_message_context` | `whatsapp__get_message_context` | Messages surrounding a specific message |
| `send_message` | `whatsapp__send_message` | Send text to phone number or group JID |
| `send_file` | `whatsapp__send_file` | Send file (image, video, document) |
| `send_audio_message` | `whatsapp__send_audio_message` | Send audio as voice message (requires ffmpeg) |
| `download_media` | `whatsapp__download_media` | Download media from a message |

See [WhatsApp MCP](tools/whatsapp-mcp/README.md) for the full setup guide, prerequisites (Go, GCC, uv), Windows CGO pain points, and known limitations.

### External MCP Server: Interview Assist

The agent can also connect to the local Interview Assist MCP wrapper for session analysis/evaluation and speech-to-text workflows.

| MCP Tool | Agent Tool Name | Description |
|----------|----------------|-------------|
| `ia_healthcheck` | `interview-assist__ia_healthcheck` | Validate Interview Assist repo/project setup |
| `ia_evaluate_session` | `interview-assist__ia_evaluate_session` | Evaluate transcript/session detection metrics |
| `ia_transcribe_once` | `interview-assist__ia_transcribe_once` | One-shot microphone/loopback transcription |
| `stt_list_devices` | `interview-assist__stt_list_devices` | List STT sources and detected endpoint devices |
| `stt_start_session` | `interview-assist__stt_start_session` | Start continuous STT polling session |
| `stt_get_updates` | `interview-assist__stt_get_updates` | Retrieve incremental STT events |
| `stt_get_session` | `interview-assist__stt_get_session` | Read STT session status/counters |
| `stt_stop_session` | `interview-assist__stt_stop_session` | Stop STT session |

See [Interview Assist MCP](tools/interview-assist-mcp/README.md) for setup and tool details.

### Configuration

See [Configuration Reference](../operations/config.md#mcpservers) for the full config format.

## Shared Utilities

### HtmlUtilities

`html_utilities.html_to_text(html)` converts HTML to readable plain text. Used by LinkedIn tools for job description extraction.

Handles:
- Block elements (p, div, h1-h6, blockquote, tr) with newlines
- Link URL preservation (`<a href="url">text</a>` becomes `text (url)`)
- List items with bullet markers
- Table cells with tab separation
- Script/style removal
- HTML entity decoding
- Whitespace normalization

### GmailParser

- `decode_body` — base64url decoding for Gmail message bodies
- `extract_text` — recursive MIME parsing, prefers HTML over plain text for multipart/alternative
- `get_header` — case-insensitive header lookup

## Adding a New Tool

1. Create a class in the `tools/` directory with matching `Tool` Protocol members
2. Define `name`, `description`, and `input_schema` properties
3. Implement `async execute()` with error handling (return error strings, don't raise)
4. If the tool modifies files, set `is_mutating = True` and implement `predict_touched_paths()` to return affected paths (enables checkpoint/rewind support)
5. Register it in `tool_registry.get_all()`

Example skeleton (read-only tool):

```python
from typing import Any


class MyTool:
    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "Does something useful."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "param": {
                    "type": "string",
                    "description": "A required parameter",
                }
            },
            "required": ["param"],
        }

    @property
    def is_mutating(self) -> bool:
        return False

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]:
        return []

    async def execute(self, tool_input: dict[str, Any]) -> str:
        param = tool_input["param"]
        try:
            # Do work
            return "Result"
        except Exception as ex:
            return f"Error: {ex}"
```

Example skeleton (file-mutating tool):

```python
from typing import Any


class MyWriteTool:
    @property
    def name(self) -> str:
        return "my_write_tool"

    @property
    def description(self) -> str:
        return "Writes content to a file."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Target file path"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        }

    @property
    def is_mutating(self) -> bool:
        return True

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]:
        path = tool_input.get("path", "")
        return [path] if path else []

    async def execute(self, tool_input: dict[str, Any]) -> str:
        try:
            # Write file
            return "Done"
        except Exception as ex:
            return f"Error: {ex}"
```
